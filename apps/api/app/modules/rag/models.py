"""RAG knowledge-base models (Phase 4C.1).

Two additive tables (Alembic migration 0003):

- ``ragdocument`` — a curated knowledge document (source, title, full
  content, metadata). Natural upsert key: (source, title).
- ``ragchunk`` — one deterministic chunk of a document, with its embedding.

``metadata`` is the attribute name ``meta`` because ``metadata`` collides
with SQLAlchemy's declarative ``metadata``. The ``embedding`` column is
``vector(EMBEDDING_DIMENSION)`` on PostgreSQL (pgvector) and a plain text
column on SQLite (tests) — see EmbeddingType below.
"""

import datetime
import uuid

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlalchemy.types import UserDefinedType
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.modules.rag.constants import EMBEDDING_DIMENSION

# JSON on SQLite, JSONB on PostgreSQL.
JSONType = JSON().with_variant(JSONB(), "postgresql")


class EmbeddingType(UserDefinedType):
    """The embedding column: ``vector(N)`` on PostgreSQL (pgvector), plain
    text on every other dialect (SQLite in tests).

    Values cross the driver boundary as pgvector's text literal form
    ``"[1.0,2.0,...]"`` in BOTH directions, so the same model works on
    PostgreSQL and SQLite WITHOUT the pgvector Python package (not a
    backend dependency). Similarity search on PostgreSQL happens in SQL
    (``<=>`` cosine distance) in service.py; on SQLite the service falls
    back to computing cosine similarity in Python (tests / pgvector-less
    dev only — see service.retrieve_chunks).
    """

    def get_col_spec(self) -> str:
        return f"vector({EMBEDDING_DIMENSION})"

    def bind_processor(self, dialect):
        def process(value):
            if value is None or isinstance(value, str):
                return value
            return "[" + ",".join(str(float(x)) for x in value) + "]"

        return process

    def result_processor(self, dialect, coltype):
        def process(value):
            if value is None:
                return None
            if isinstance(value, (list, tuple)):
                return [float(x) for x in value]
            inner = str(value).strip().lstrip("[").rstrip("]")
            return [float(x) for x in inner.split(",") if x.strip()] if inner else []

        return process


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class RagDocument(SQLModel, table=True):
    """A curated knowledge-base document (SRS §13: coaching knowledge)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    title: str = Field(nullable=False)
    source: str = Field(nullable=False, index=True)
    source_url: str | None = Field(default=None)
    content: str = Field(nullable=False)
    meta: dict | None = Field(default=None, sa_column=Column("metadata", JSONType))
    created_at: datetime.datetime = Field(default_factory=_utcnow)
    updated_at: datetime.datetime = Field(default_factory=_utcnow)


class RagChunk(SQLModel, table=True):
    """One deterministic chunk of a RagDocument, with its embedding.

    (document_id, chunk_index) is unique: re-ingesting a document replaces
    its chunks wholesale, and chunk indexes are stable for identical input
    (see chunking.chunk_text).
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    document_id: uuid.UUID = Field(foreign_key="ragdocument.id", index=True)
    chunk_index: int = Field(nullable=False)
    content: str = Field(nullable=False)
    meta: dict | None = Field(default=None, sa_column=Column("metadata", JSONType))
    embedding: list[float] | None = Field(
        default=None, sa_column=Column("embedding", EmbeddingType())
    )
    created_at: datetime.datetime = Field(default_factory=_utcnow)

    __table_args__ = (UniqueConstraint("document_id", "chunk_index"),)
