"""Phase 4C.1 RAG tests: chunking, ingestion, provider abstraction,
retrieval, API surface, and the Alembic migration.

⚠ Everything here is TEST-FIXTURE data. The "embeddings" are deterministic
geometric basis vectors (not semantic embeddings from any model), and the
knowledge documents are clearly-marked placeholder text — never real fitness
or medical advice. No real user data and no external AI provider is touched.
"""
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, select

from app.core.database import engine
from app.modules.rag import service
from app.modules.rag.chunking import chunk_text
from app.modules.rag.constants import CHUNK_SIZE, EMBEDDING_DIMENSION
from app.modules.rag.models import RagChunk, RagDocument
from app.modules.rag.providers import (
    EmbeddingProvider,
    EmbeddingProviderNotConfigured,
    get_embedding_provider,
)

API_DIR = Path(__file__).resolve().parents[1]

# ─────────────────────────────────────────────────────────────────────────────
# TEST FIXTURES — placeholder knowledge content, NOT authoritative advice
# ─────────────────────────────────────────────────────────────────────────────

FIXTURE_DOC = (
    "TEST FIXTURE — FitQuest RAG pipeline verification document. "
    "This is placeholder coaching-style text for automated tests only; "
    "it is not fitness, medical, or professional advice of any kind.\n\n"
    "Walking pace. A brisk walking pace is a simple, sustainable way to "
    "accumulate daily steps. Test-fixture placeholder text.\n\n"
    "Recovery basics. Rest days let the body adapt between active days. "
    "Test-fixture placeholder text."
)


def basis(index: int, scale: float = 1.0) -> list[float]:
    """Deterministic geometric vector: one non-zero component (TEST FIXTURE
    ONLY — this is NOT a semantic embedding; it exists so cosine ordering,
    filters, and top_k can be asserted exactly)."""
    vector = [0.0] * EMBEDDING_DIMENSION
    vector[index] = scale
    return vector


class FixtureEmbeddingProvider:
    """TEST-ONLY EmbeddingProvider: maps chunk text -> a chosen vector.

    Never used in production code — the real provider arrives in Phase
    4C.2. Keys are exact chunk contents (chunking is deterministic, so the
    tests always know them); unmapped texts get the default vector."""

    def __init__(self, mapping: dict | None = None, default: list[float] | None = None):
        self.dimension = EMBEDDING_DIMENSION
        self.mapping = mapping or {}
        self.default = default if default is not None else basis(0)
        self.seen_texts: list[list[str]] = []

    def embed_texts(self, texts):
        self.seen_texts.append(list(texts))
        return [list(self.mapping.get(text, self.default)) for text in texts]


@pytest.fixture()
def db():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


# ─────────────────────────────────────────────────────────────────────────────
# Chunking (pure)
# ─────────────────────────────────────────────────────────────────────────────


def test_chunking_single_short_paragraph_returns_itself():
    assert chunk_text("one paragraph") == ["one paragraph"]


def test_chunking_exact_example_with_and_without_overlap():
    content = "AAAA BBBB\n\nCCCC DDDD"
    # Each paragraph is 9 chars; with chunk_size 10 they cannot be packed
    # together (9 + 2 + 9 > 10), so they become two chunks.
    assert chunk_text(content, chunk_size=10, overlap=0) == ["AAAA BBBB", "CCCC DDDD"]
    # With overlap 4 the tail of chunk 0 ("BBBB" — no space to snap past)
    # is prepended to chunk 1.
    assert chunk_text(content, chunk_size=10, overlap=4) == [
        "AAAA BBBB",
        "BBBB\n\nCCCC DDDD",
    ]


def test_chunking_is_deterministic():
    once = chunk_text(FIXTURE_DOC, chunk_size=200, overlap=50)
    twice = chunk_text(FIXTURE_DOC, chunk_size=200, overlap=50)
    assert once == twice and len(once) > 1  # non-trivially chunked


def test_chunking_preserves_document_order():
    chunks = chunk_text(FIXTURE_DOC, chunk_size=200, overlap=50)
    assert chunks[0].startswith("TEST FIXTURE")
    assert chunks[-1].endswith("Test-fixture placeholder text.")
    # Chunk indexes are the list positions: stable by construction.


def test_chunking_never_cuts_words_in_oversized_paragraphs():
    words = [f"word{i:03d}" for i in range(60)]  # each word is 7 chars
    content = " ".join(words)
    chunks = chunk_text(content, chunk_size=30, overlap=0)
    assert len(chunks) > 1
    seen: list[str] = []
    for chunk in chunks:
        seen.extend(chunk.split(" "))
    assert seen == words  # every word present, in order, uncut


def test_chunking_empty_and_whitespace_yield_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n\n \t \n\n") == []


def test_chunking_rejects_invalid_parameters():
    with pytest.raises(ValueError):
        chunk_text("text", chunk_size=0)
    with pytest.raises(ValueError):
        chunk_text("text", chunk_size=10, overlap=-1)
    with pytest.raises(ValueError):
        chunk_text("text", chunk_size=10, overlap=10)  # overlap must be < size
    with pytest.raises(TypeError):
        chunk_text(123)


def test_chunks_respect_soft_size_bound():
    chunks = chunk_text(FIXTURE_DOC, chunk_size=100, overlap=20)
    # New content per chunk <= chunk_size; carried overlap can add up to
    # `overlap` characters plus the separator.
    assert all(len(c) <= 100 + 20 + 2 for c in chunks)


# ─────────────────────────────────────────────────────────────────────────────
# Ingestion & persistence
# ─────────────────────────────────────────────────────────────────────────────


def test_ingest_persists_document_and_chunks(db):
    provider = FixtureEmbeddingProvider()
    document = service.ingest_document(
        db, title="Fixture warmup guide", source="fitquest-test-fixtures",
        content=FIXTURE_DOC, provider=provider,
    )

    stored = db.get(RagDocument, document.id)
    assert stored is not None and stored.content == FIXTURE_DOC
    chunks = db.exec(
        select(RagChunk).where(RagChunk.document_id == document.id).order_by(RagChunk.chunk_index)
    ).all()
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert len(chunks) == len(chunk_text(FIXTURE_DOC))
    # The provider embedded every chunk, once, in order.
    assert provider.seen_texts == [[c.content for c in chunks]]
    # Embeddings round-trip through the column type as vectors.
    assert all(c.embedding is not None and len(c.embedding) == EMBEDDING_DIMENSION for c in chunks)


def test_reingest_same_document_is_an_idempotent_upsert(db):
    provider = FixtureEmbeddingProvider()
    first = service.ingest_document(
        db, title="Fixture doc", source="fitquest-test-fixtures",
        content=FIXTURE_DOC, provider=provider,
    )
    second = service.ingest_document(
        db, title="Fixture doc", source="fitquest-test-fixtures",
        content=FIXTURE_DOC, provider=provider,
    )
    assert second.id == first.id  # same (source, title) -> same document
    chunks = db.exec(select(RagChunk).where(RagChunk.document_id == first.id)).all()
    assert len(chunks) == len(chunk_text(FIXTURE_DOC))  # replaced, not duplicated

    # Changing the content replaces the chunks wholesale.
    shorter = "TEST FIXTURE — single short replacement paragraph."
    service.ingest_document(
        db, title="Fixture doc", source="fitquest-test-fixtures",
        content=shorter, provider=provider,
    )
    chunks = db.exec(select(RagChunk).where(RagChunk.document_id == first.id)).all()
    assert [c.chunk_index for c in chunks] == [0]
    assert chunks[0].content == shorter


def test_ingest_rejects_empty_content_and_blank_fields(db):
    provider = FixtureEmbeddingProvider()
    for bad_content in ("", "   \n\n "):
        with pytest.raises(ValueError, match="nothing to ingest"):
            service.ingest_document(
                db, title="t", source="s", content=bad_content, provider=provider
            )
    with pytest.raises(ValueError, match="non-empty"):
        service.ingest_document(
            db, title="  ", source="s", content="valid", provider=provider
        )


def test_ingest_rejects_provider_dimension_mismatch(db):
    class WrongDimensionProvider(FixtureEmbeddingProvider):
        def __init__(self):
            super().__init__()
            self.dimension = 7  # anything but EMBEDDING_DIMENSION

    with pytest.raises(ValueError, match="dimension"):
        service.ingest_document(
            db, title="t", source="s", content="valid content",
            provider=WrongDimensionProvider(),
        )


def test_chunks_inherit_document_metadata(db):
    provider = FixtureEmbeddingProvider()
    document = service.ingest_document(
        db, title="Fixture doc", source="fitquest-test-fixtures",
        content=FIXTURE_DOC, provider=provider,
        document_metadata={"topic": "warmup", "kind": "fixture"},
    )
    chunk = db.exec(select(RagChunk).where(RagChunk.document_id == document.id)).first()
    assert chunk.meta == {"topic": "warmup", "kind": "fixture"}


# ─────────────────────────────────────────────────────────────────────────────
# Provider abstraction
# ─────────────────────────────────────────────────────────────────────────────


def test_fixture_provider_satisfies_the_protocol():
    assert isinstance(FixtureEmbeddingProvider(), EmbeddingProvider)


def test_no_embedding_provider_is_configured_without_a_key(monkeypatch):
    # Hermetic since 4C.2: a real GEMINI_API_KEY may exist in the
    # developer's .env, so the "unconfigured" state is forced explicitly.
    from app.core.config import settings

    monkeypatch.setattr(settings, "gemini_api_key", None)
    with pytest.raises(EmbeddingProviderNotConfigured):
        get_embedding_provider()


# ─────────────────────────────────────────────────────────────────────────────
# Retrieval
# ─────────────────────────────────────────────────────────────────────────────


def _seed_documents(db):
    """Three docs; chunk embeddings chosen so cosine order is known."""
    content = "TEST FIXTURE — placeholder text for retrieval tests."
    service.ingest_document(
        db, title="alpha", source="src-a", content=content,
        provider=FixtureEmbeddingProvider(mapping={content: basis(0)}),
        document_metadata={"topic": "warmup"},
    )
    service.ingest_document(
        db, title="beta", source="src-b", content=content,
        provider=FixtureEmbeddingProvider(mapping={content: basis(1)}),
        document_metadata={"topic": "recovery"},
    )
    # Same direction as alpha (cosine 1) mixed with beta (cosine 1/sqrt(2)).
    mixed = [
        1.0 / math.sqrt(2.0) if i in (0, 1) else 0.0
        for i in range(EMBEDDING_DIMENSION)
    ]
    service.ingest_document(
        db, title="gamma", source="src-a", content=content,
        provider=FixtureEmbeddingProvider(mapping={content: mixed}),
        document_metadata={"topic": "warmup"},
    )


def test_retrieval_orders_by_cosine_similarity(db):
    _seed_documents(db)
    results = service.retrieve_chunks(db, query_embedding=basis(0), top_k=10)
    assert [r.document_title for r in results] == ["alpha", "gamma", "beta"]
    assert results[0].similarity == pytest.approx(1.0)
    assert results[1].similarity == pytest.approx(1.0 / math.sqrt(2.0), abs=1e-6)
    assert results[2].similarity == pytest.approx(0.0, abs=1e-9)


def test_retrieval_top_k_limits_results(db):
    _seed_documents(db)
    assert len(service.retrieve_chunks(db, query_embedding=basis(0), top_k=2)) == 2
    assert len(service.retrieve_chunks(db, query_embedding=basis(0), top_k=1)) == 1


def test_retrieval_source_filter(db):
    _seed_documents(db)
    results = service.retrieve_chunks(db, query_embedding=basis(1), top_k=10, source="src-a")
    assert [r.document_source for r in results] == ["src-a", "src-a"]
    assert {r.document_title for r in results} == {"alpha", "gamma"}


def test_retrieval_metadata_filter(db):
    _seed_documents(db)
    results = service.retrieve_chunks(
        db, query_embedding=basis(1), top_k=10, metadata_filters={"topic": "warmup"}
    )
    assert {r.document_title for r in results} == {"alpha", "gamma"}


def test_retrieval_ties_break_deterministically(db):
    content_a = "TEST FIXTURE A — placeholder."
    content_b = "TEST FIXTURE B — placeholder."
    service.ingest_document(
        db, title="tie doc", source="src-tie",
        content=content_a + "\n\n" + content_b,
        provider=FixtureEmbeddingProvider(
            mapping={content_a: basis(3), content_b: basis(3)}
        ),
        chunk_size=30, overlap=0,  # force one chunk per fixture paragraph
    )
    results = service.retrieve_chunks(db, query_embedding=basis(3), top_k=10)
    assert [r.chunk_index for r in results] == [0, 1]


def test_retrieval_validates_the_query_embedding(db):
    with pytest.raises(ValueError, match="width"):
        service.retrieve_chunks(db, query_embedding=[1.0, 2.0], top_k=5)
    bad = basis(0)
    bad[0] = math.inf
    with pytest.raises(ValueError, match="non-finite"):
        service.retrieve_chunks(db, query_embedding=bad, top_k=5)
    with pytest.raises(ValueError, match="top_k"):
        service.retrieve_chunks(db, query_embedding=basis(0), top_k=0)


def test_retrieval_on_an_empty_knowledge_base(db):
    assert service.retrieve_chunks(db, query_embedding=basis(0), top_k=5) == []


# ─────────────────────────────────────────────────────────────────────────────
# API surface (HTTP)
# ─────────────────────────────────────────────────────────────────────────────


def test_retrieve_endpoint_ranks_and_returns_chunks(client):
    with Session(engine) as session:  # client fixture created the tables
        _seed_documents(session)
    response = client.post(
        "/api/v1/rag/retrieve",
        json={"query_embedding": basis(0), "top_k": 3},
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert [r["document_title"] for r in results] == ["alpha", "gamma", "beta"]
    assert results[0]["similarity"] == pytest.approx(1.0)


def test_retrieve_endpoint_applies_filters(client):
    with Session(engine) as session:
        _seed_documents(session)
    response = client.post(
        "/api/v1/rag/retrieve",
        json={"query_embedding": basis(0), "top_k": 10, "source": "src-b"},
    )
    assert response.status_code == 200
    assert [r["document_title"] for r in response.json()["results"]] == ["beta"]


def test_retrieve_endpoint_validates_request(client):
    assert client.post(
        "/api/v1/rag/retrieve", json={"query_embedding": [1.0, 2.0], "top_k": 5}
    ).status_code == 422  # wrong width
    assert client.post(
        "/api/v1/rag/retrieve", json={"query_embedding": basis(0), "top_k": 0}
    ).status_code == 422  # top_k out of range


def test_documents_endpoint_lists_ingested_documents(client):
    with Session(engine) as session:
        service.ingest_document(
            session, title="Fixture doc", source="fitquest-test-fixtures",
            content=FIXTURE_DOC, provider=FixtureEmbeddingProvider(),
        )
    response = client.get("/api/v1/rag/documents")
    assert response.status_code == 200
    documents = response.json()
    assert len(documents) == 1
    assert documents[0]["title"] == "Fixture doc"
    assert documents[0]["chunk_count"] == len(chunk_text(FIXTURE_DOC))


def test_ingestion_endpoint_requires_authentication_and_admin(anon_client, client):
    """F-18 — the ingestion route is closed to everyone but an allow-listed admin.

    Two separate refusals, which is the point: authentication establishes WHO
    you are, the allow-list decides whether that is enough. A signed-in user is
    not automatically able to write to the shared knowledge base.
    """
    payload = {"title": "x", "source": "y", "content": "z"}

    # No token at all → 401 from the router-level auth dependency.
    assert anon_client.post("/api/v1/rag/documents", json=payload).status_code == 401
    # A valid token, but the account is not on ADMIN_USER_IDS → 403.
    assert client.post("/api/v1/rag/documents", json=payload).status_code == 403


def test_admin_can_ingest_through_the_endpoint(admin, client, monkeypatch):
    """The allow-listed caller ingests for real (F-18).

    The provider is faked — no external AI call — so this exercises the route,
    the service and the read-back without leaving the machine.
    """
    from app.modules.rag import router as rag_router

    monkeypatch.setattr(
        rag_router, "get_embedding_provider", lambda: FixtureEmbeddingProvider()
    )

    response = client.post(
        "/api/v1/rag/documents",
        json={
            "title": "Fixture doc",
            "source": "fitquest-test-fixtures",
            "content": FIXTURE_DOC,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == "Fixture doc"
    assert body["chunk_count"] == len(chunk_text(FIXTURE_DOC))
    # It really landed: the listing endpoint sees it.
    assert [d["title"] for d in client.get("/api/v1/rag/documents").json()] == [
        "Fixture doc"
    ]


def test_ingestion_rejects_an_empty_document(admin, client):
    """A blank title/source/content is a 422, checked before any provider call."""
    response = client.post(
        "/api/v1/rag/documents",
        json={"title": "  ", "source": "y", "content": "z"},
    )
    assert response.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# Alembic migration
# ─────────────────────────────────────────────────────────────────────────────


def test_rag_migration_applies_and_reverts_cleanly(tmp_path):
    """The RAG migration's up and down are clean, pinned by REVISION.

    M11 — both ends are explicit revisions rather than ``head``/``-1``.
    ``-1`` counts backwards from whatever is currently on top, so adding 0004
    above the RAG revision silently turned the revert into "undo 0004" and the
    assertions below started describing the wrong tables. Pinning the ends
    keeps this test about the RAG migration no matter what is stacked above it.

    SQLite path only — the pgvector extension/HNSW steps are PostgreSQL-only
    and are skipped.
    """
    RAG_REVISION = "0003"  # creates ragdocument + ragchunk
    RAG_PARENT = "0002"  # the revision immediately below it

    db_url = f"sqlite:///{(tmp_path / 'rag_migration_check.db').as_posix()}"
    env = {**os.environ, "DATABASE_URL": db_url}

    def run_alembic(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
            cwd=API_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

    # Reach HEAD, not just the RAG revision: proves the migration applies on
    # the path a real deployment takes, with 0004 stacked on top of it.
    upgrade = run_alembic("upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr

    from sqlalchemy import create_engine, inspect

    inspection_engine = create_engine(db_url)
    try:
        inspector = inspect(inspection_engine)
        tables = set(inspector.get_table_names())
        assert {"ragdocument", "ragchunk"} <= tables
        doc_columns = {c["name"] for c in inspector.get_columns("ragdocument")}
        assert doc_columns == {
            "id", "title", "source", "source_url", "content",
            "metadata", "created_at", "updated_at",
        }
        chunk_columns = {c["name"] for c in inspector.get_columns("ragchunk")}
        assert chunk_columns == {
            "id", "document_id", "chunk_index", "content",
            "metadata", "embedding", "created_at",
        }
        pk = set(inspector.get_pk_constraint("ragchunk")["constrained_columns"])
        assert pk == {"id"}
        # (document_id, chunk_index) is unique — chunk upserts stay stable.
        uniques = {
            frozenset(c["column_names"])
            for c in inspector.get_unique_constraints("ragchunk")
        }
        assert frozenset({"document_id", "chunk_index"}) in uniques
    finally:
        inspection_engine.dispose()

    # Revert to the revision BELOW the RAG migration — an explicit target, so
    # this removes the RAG tables whether or not anything sits above them.
    downgrade = run_alembic("downgrade", RAG_PARENT)
    assert downgrade.returncode == 0, downgrade.stderr
    check_engine = create_engine(db_url)
    try:
        remaining = set(inspect(check_engine).get_table_names())
        assert "ragchunk" not in remaining
        assert "ragdocument" not in remaining
        # The 4B.5 telemetry table is untouched by the RAG downgrade.
        assert "userdailyactivity" in remaining
    finally:
        check_engine.dispose()
