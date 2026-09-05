"""RAG ingestion + similarity retrieval services (Phase 4C.1).

Ingestion (service-level only — no public HTTP endpoint, because auth is
deferred in FitQuest and document administration should not be on the wire
yet): ``ingest_document`` chunk + embed + upsert, idempotent on the natural
key (source, title).

Retrieval: ``retrieve_chunks`` ranks chunks by cosine similarity to a query
embedding, with optional source/metadata filters, top_k, and (Phase 4C.2)
a minimum-similarity threshold — independent of the HTTP layer.
``retrieve_chunks_for_text`` runs the full text → embedding → search flow
using an injected provider.

Two retrieval engines, selected by the session's dialect:

- PostgreSQL (production / Supabase): pgvector's ``<=>`` cosine distance
  computed IN the database, backed by the HNSW index from migration 0003.
- any other dialect (SQLite — the test suite): a portable pure-Python
  cosine over the stored vectors. This is the same ranking definition,
  evaluated client-side; it is a test/dev convenience, not a fake — the
  vectors are whatever was actually persisted.

The tests exercise the portable path; the PostgreSQL path is exercised the
first time the migration runs against Supabase (deferred, like 4B.5 — see
module README).
"""

from __future__ import annotations

import datetime
import json
import math
import uuid
from typing import Optional, Sequence

from sqlalchemy import delete, func, text
from sqlmodel import Session, select

from app.modules.rag.chunking import chunk_text
from app.modules.rag.constants import CHUNK_OVERLAP, CHUNK_SIZE, EMBEDDING_DIMENSION
from app.modules.rag.models import RagChunk, RagDocument
from app.modules.rag.providers import EmbeddingProvider
from app.modules.rag.schemas import DocumentInfo, RetrievedChunk

MAX_TOP_K = 100


# ─────────────────────────────────────────────────────────────────────────────
# Ingestion
# ─────────────────────────────────────────────────────────────────────────────


def _validate_provider(provider: EmbeddingProvider) -> None:
    if provider.dimension != EMBEDDING_DIMENSION:
        raise ValueError(
            f"provider dimension {provider.dimension} does not match the "
            f"persistence layer's EMBEDDING_DIMENSION={EMBEDDING_DIMENSION} "
            "(app/modules/rag/constants.py)"
        )


def ingest_document(
    db: Session,
    *,
    title: str,
    source: str,
    content: str,
    provider: EmbeddingProvider,
    source_url: Optional[str] = None,
    document_metadata: Optional[dict] = None,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> RagDocument:
    """Chunk, embed, and upsert one document.

    Idempotent on (source, title): re-ingesting the same document replaces
    its content, metadata, and ALL of its chunks (chunk indexes are stable
    for identical content — see chunking.py). The caller supplies the
    embedding provider (injectable by design; none is configured in 4C.1).
    """
    if not title.strip() or not source.strip():
        raise ValueError("title and source must be non-empty")

    chunks = chunk_text(content, chunk_size=chunk_size, overlap=overlap)
    if not chunks:
        raise ValueError("content is empty or whitespace-only — nothing to ingest")

    _validate_provider(provider)
    embeddings = provider.embed_texts(chunks)
    if len(embeddings) != len(chunks):
        raise ValueError(
            f"provider returned {len(embeddings)} embeddings for "
            f"{len(chunks)} chunks"
        )
    for i, vector in enumerate(embeddings):
        if len(vector) != EMBEDDING_DIMENSION:
            raise ValueError(
                f"embedding {i} has width {len(vector)}, expected "
                f"{EMBEDDING_DIMENSION}"
            )

    now = datetime.datetime.now(datetime.timezone.utc)
    document = db.exec(
        select(RagDocument).where(
            RagDocument.source == source, RagDocument.title == title
        )
    ).first()
    if document is None:
        document = RagDocument(
            title=title, source=source, source_url=source_url,
            content=content, meta=document_metadata, created_at=now, updated_at=now,
        )
        db.add(document)
        db.flush()  # assign document.id before the FK below
    else:
        document.title = title
        document.source = source
        document.source_url = source_url
        document.content = content
        document.meta = document_metadata
        document.updated_at = now
        db.add(document)
        db.execute(delete(RagChunk).where(RagChunk.document_id == document.id))

    for index, (chunk_content, embedding) in enumerate(zip(chunks, embeddings)):
        db.add(
            RagChunk(
                document_id=document.id,
                chunk_index=index,
                content=chunk_content,
                # Chunks inherit the document's metadata (a copy) so
                # retrieval-time metadata filters work at chunk level in v1.
                meta=dict(document_metadata) if document_metadata else None,
                embedding=list(embedding),
                created_at=now,
            )
        )

    db.commit()
    db.refresh(document)
    return document


def list_documents(db: Session) -> list[DocumentInfo]:
    """Read-only listing with chunk counts (for the GET endpoint)."""
    counts = dict(
        db.exec(
            select(RagChunk.document_id, func.count(RagChunk.id)).group_by(
                RagChunk.document_id
            )
        ).all()
    )
    documents = db.exec(select(RagDocument).order_by(RagDocument.source, RagDocument.title)).all()
    return [
        DocumentInfo(
            id=document.id,
            title=document.title,
            source=document.source,
            source_url=document.source_url,
            chunk_count=counts.get(document.id, 0),
            created_at=document.created_at,
            updated_at=document.updated_at,
        )
        for document in documents
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Retrieval
# ─────────────────────────────────────────────────────────────────────────────


def _validate_query_embedding(query_embedding: Sequence[float]) -> list[float]:
    if len(query_embedding) != EMBEDDING_DIMENSION:
        raise ValueError(
            f"query_embedding has width {len(query_embedding)}, expected "
            f"{EMBEDDING_DIMENSION}"
        )
    vector = [float(x) for x in query_embedding]
    if not all(math.isfinite(x) for x in vector):
        raise ValueError("query_embedding contains non-finite values")
    return vector


def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0  # undefined direction — treat as "no similarity"
    return dot / (norm_a * norm_b)


def _metadata_matches(chunk_meta: Optional[dict], filters: dict) -> bool:
    meta = chunk_meta or {}
    return all(key in meta and meta[key] == value for key, value in filters.items())


def retrieve_chunks(
    db: Session,
    *,
    query_embedding: Sequence[float],
    top_k: int = 5,
    source: Optional[str] = None,
    metadata_filters: Optional[dict] = None,
    min_similarity: Optional[float] = None,
) -> list[RetrievedChunk]:
    """Return the up-to-``top_k`` chunks most similar (cosine) to the embedding.

    Filters: ``source`` matches the document's source exactly;
    ``metadata_filters`` matches chunk metadata as a subset (JSONB ``@>``
    on PostgreSQL, dict containment on the portable path). Results are
    ordered by similarity descending, with (document_id, chunk_index) as a
    deterministic tie-break. Independent of the HTTP layer.

    ``min_similarity`` (Phase 4C.2): chunks scoring below the threshold
    are dropped — unrelated chunks are never silently returned. Applied
    inside the SQL on PostgreSQL and after scoring on the portable path,
    BEFORE top_k truncation, so a filtered result may contain fewer than
    top_k chunks (including zero).
    """
    vector = _validate_query_embedding(query_embedding)
    if not 1 <= top_k <= MAX_TOP_K:
        raise ValueError(f"top_k must be in 1..{MAX_TOP_K}, got {top_k}")
    if min_similarity is not None and not -1.0 <= min_similarity <= 1.0:
        raise ValueError(
            f"min_similarity must be within cosine range [-1, 1], got {min_similarity}"
        )

    if db.get_bind().dialect.name == "postgresql":
        return _retrieve_postgres(
            db, vector, top_k, source, metadata_filters, min_similarity
        )
    return _retrieve_portable(db, vector, top_k, source, metadata_filters, min_similarity)


def retrieve_chunks_for_text(
    db: Session,
    *,
    query_text: str,
    provider: EmbeddingProvider,
    top_k: int = 5,
    source: Optional[str] = None,
    metadata_filters: Optional[dict] = None,
    min_similarity: Optional[float] = None,
) -> list[RetrievedChunk]:
    """Full text→embedding→similarity retrieval flow (Phase 4C.2).

    Embeds ``query_text`` with the injected provider (which validates the
    vector width against EMBEDDING_DIMENSION), then delegates to
    ``retrieve_chunks``. Kept here so both the coach service and the
    ingestion tooling share one retrieval entry point.
    """
    if not query_text.strip():
        raise ValueError("query_text must be non-empty")
    _validate_provider(provider)
    embedding = provider.embed_texts([query_text])[0]
    return retrieve_chunks(
        db,
        query_embedding=embedding,
        top_k=top_k,
        source=source,
        metadata_filters=metadata_filters,
        min_similarity=min_similarity,
    )


def _retrieve_postgres(
    db: Session,
    vector: list[float],
    top_k: int,
    source: Optional[str],
    metadata_filters: Optional[dict],
    min_similarity: Optional[float],
) -> list[RetrievedChunk]:
    """pgvector cosine distance, computed in the database (HNSW-indexed)."""
    query_literal = "[" + ",".join(str(x) for x in vector) + "]"
    meta_literal = json.dumps(metadata_filters) if metadata_filters else None
    statement = text(
        """
        SELECT c.id AS chunk_id, c.document_id, c.chunk_index, c.content,
               c.metadata AS metadata, d.title AS document_title,
               d.source AS document_source,
               1 - (c.embedding <=> CAST(:query AS vector)) AS similarity
        FROM ragchunk c
        JOIN ragdocument d ON d.id = c.document_id
        WHERE c.embedding IS NOT NULL
          AND (:source IS NULL OR d.source = :source)
          AND (:meta IS NULL OR c.metadata @> CAST(:meta AS jsonb))
          AND (:min_sim IS NULL OR 1 - (c.embedding <=> CAST(:query AS vector)) >= :min_sim)
        ORDER BY similarity DESC, c.document_id, c.chunk_index
        LIMIT :top_k
        """
    )
    rows = db.execute(
        statement,
        {
            "query": query_literal,
            "source": source,
            "meta": meta_literal,
            "top_k": top_k,
            "min_sim": min_similarity,
        },
    ).mappings()
    return [
        RetrievedChunk(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            document_title=row["document_title"],
            document_source=row["document_source"],
            chunk_index=row["chunk_index"],
            content=row["content"],
            similarity=float(row["similarity"]),
            metadata=row["metadata"],
        )
        for row in rows
    ]


def _retrieve_portable(
    db: Session,
    vector: list[float],
    top_k: int,
    source: Optional[str],
    metadata_filters: Optional[dict],
    min_similarity: Optional[float],
) -> list[RetrievedChunk]:
    """Pure-Python cosine ranking (SQLite tests / pgvector-less dev)."""
    statement = select(RagChunk, RagDocument).join(
        RagDocument, RagDocument.id == RagChunk.document_id
    )
    if source is not None:
        statement = statement.where(RagDocument.source == source)

    scored: list[tuple[float, RagChunk, RagDocument]] = []
    for chunk, document in db.exec(statement).all():
        if chunk.embedding is None:
            continue
        if metadata_filters and not _metadata_matches(chunk.meta, metadata_filters):
            continue
        similarity = _cosine_similarity(vector, chunk.embedding)
        # Threshold BEFORE top_k truncation — see retrieve_chunks docstring.
        if min_similarity is not None and similarity < min_similarity:
            continue
        scored.append((similarity, chunk, document))

    scored.sort(key=lambda item: (-item[0], item[1].document_id, item[1].chunk_index))
    return [
        RetrievedChunk(
            chunk_id=chunk.id,
            document_id=document.id,
            document_title=document.title,
            document_source=document.source,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            similarity=round(similarity, 6),
            metadata=chunk.meta,
        )
        for similarity, chunk, document in scored[:top_k]
    ]
