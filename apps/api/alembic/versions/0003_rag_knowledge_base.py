"""RAG knowledge base: ragdocument + ragchunk (Phase 4C.1)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-05

Additive migration for the RAG knowledge base (SRS §13): a curated document
table and its embedded chunks, using pgvector on PostgreSQL.

- ``ragdocument``: (source, title) is the natural upsert key; ``source`` is
  indexed for source-filtered retrieval.
- ``ragchunk``: FK to ragdocument, unique (document_id, chunk_index) so chunk
  ingestion is idempotent, and an ``embedding vector(1536)`` column.
- pgvector extension + HNSW cosine index are created ONLY on PostgreSQL —
  the same migration runs on SQLite (tests) where the vector column is just
  text (see app/modules/rag/models.py EmbeddingType).

EMBEDDING_DIMENSION is frozen HERE at 1536 (the value in
app/modules/rag/constants.py when this migration was written). Migrations
must not read live settings: changing the dimension later means a NEW
migration (alter column + re-embed every chunk), not editing this file.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.types import UserDefinedType

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen at migration-creation time — keep in sync with a deliberate
# decision, never a silent edit (see module docstring).
EMBEDDING_DIMENSION = 1536


class _VectorType(UserDefinedType):
    """vector(N) on PostgreSQL; SQLite accepts it as an opaque type name."""

    def get_col_spec(self) -> str:
        return f"vector({EMBEDDING_DIMENSION})"


def upgrade() -> None:
    bind = op.get_bind()
    is_postgresql = bind.dialect.name == "postgresql"

    if is_postgresql:
        # Supabase ships pgvector; enabling is idempotent. On SQLite (tests)
        # this is skipped — the column degrades to plain text.
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "ragdocument",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ragdocument_source"), "ragdocument", ["source"], unique=False)

    op.create_table(
        "ragchunk",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"), nullable=True),
        sa.Column("embedding", _VectorType(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["ragdocument.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_ragchunk_document_chunk_index"),
    )
    op.create_index(op.f("ix_ragchunk_document_id"), "ragchunk", ["document_id"], unique=False)

    if is_postgresql:
        # Approximate nearest-neighbour cosine index. HNSW (pgvector >= 0.5)
        # is chosen over IVFFlat because it needs no pre-training rows and
        # stays valid as the (currently empty) corpus grows.
        op.execute(
            "CREATE INDEX ix_ragchunk_embedding_hnsw ON ragchunk "
            "USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgresql = bind.dialect.name == "postgresql"

    if is_postgresql:
        op.execute("DROP INDEX IF EXISTS ix_ragchunk_embedding_hnsw")
    op.drop_index(op.f("ix_ragchunk_document_id"), table_name="ragchunk")
    op.drop_table("ragchunk")
    op.drop_index(op.f("ix_ragdocument_source"), table_name="ragdocument")
    op.drop_table("ragdocument")
