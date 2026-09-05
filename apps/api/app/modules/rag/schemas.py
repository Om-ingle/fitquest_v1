"""Pydantic schemas for the RAG API surface (Phase 4C.1).

Minimal by design: a retrieval request/response (useful for testing the
pipeline without any embedding provider — the caller supplies the query
embedding) and a read-only document listing. There is deliberately NO
public ingestion endpoint: ingestion is service-level only (see
service.ingest_document and the module README — auth is deferred in
FitQuest, so administrative endpoints stay off the wire).
"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from app.modules.rag.constants import EMBEDDING_DIMENSION


class RetrievalRequest(BaseModel):
    """Vector search over ragchunk. The caller supplies the query embedding
    (the coach flow produces it server-side via the configured provider)."""

    query_embedding: list[float]
    top_k: int = 5
    source: Optional[str] = None
    metadata: Optional[dict] = None
    # Phase 4C.2: chunks below this cosine similarity are excluded (None →
    # no threshold; the coach flow uses the RAG_SIMILARITY_THRESHOLD setting).
    min_similarity: Optional[float] = None

    @field_validator("query_embedding")
    @classmethod
    def _embedding_width(cls, value: list[float]) -> list[float]:
        if len(value) != EMBEDDING_DIMENSION:
            raise ValueError(
                f"query_embedding has width {len(value)}, expected "
                f"{EMBEDDING_DIMENSION} (app/modules/rag/constants.py)"
            )
        return value

    @field_validator("top_k")
    @classmethod
    def _top_k_sane(cls, value: int) -> int:
        if not 1 <= value <= 100:
            raise ValueError(f"top_k must be in 1..100, got {value}")
        return value

    @field_validator("min_similarity")
    @classmethod
    def _min_similarity_sane(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and not -1.0 <= value <= 1.0:
            raise ValueError(f"min_similarity must be in [-1, 1], got {value}")
        return value


class RetrievedChunk(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    document_source: str
    chunk_index: int
    content: str
    similarity: float
    metadata: Optional[dict] = None


class RetrievalResponse(BaseModel):
    results: list[RetrievedChunk]


class DocumentInfo(BaseModel):
    id: uuid.UUID
    title: str
    source: str
    source_url: Optional[str] = None
    chunk_count: int
    created_at: datetime
    updated_at: datetime
