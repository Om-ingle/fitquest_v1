"""Phase 4C.2 retrieval wiring: minimum-similarity threshold and the
text→embedding→search flow. Same fixture-embedding approach as
tests/test_rag.py — geometric basis vectors, no network.
"""
import math

import pytest
from sqlmodel import Session, SQLModel

from app.core.database import engine
from app.modules.rag import service
from app.modules.rag.constants import EMBEDDING_DIMENSION
from app.modules.rag.providers import EmbeddingProvider


def basis(index: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSION
    vector[index] = 1.0
    return vector


class FixtureEmbeddingProvider:
    """TEST-ONLY: maps the single query text to a chosen vector."""

    def __init__(self, query_vector=None):
        self.dimension = EMBEDDING_DIMENSION
        self.query_vector = query_vector or basis(0)

    def embed_texts(self, texts):
        assert len(texts) == 1, "fixture provider embeds exactly the query"
        return [list(self.query_vector)]


class WrongDimensionProvider:
    dimension = 7

    def embed_texts(self, texts):
        return [[0.0] * 7 for _ in texts]


@pytest.fixture()
def db():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


def _seed(db):
    """Three documents with known cosine order relative to basis(0):
    alpha=1.0, gamma=1/sqrt(2), beta=0.0."""
    content = "TEST FIXTURE — placeholder text for threshold tests."
    for title, source, vector in [
        ("alpha", "src-a", basis(0)),
        ("beta", "src-b", basis(1)),
        (
            "gamma",
            "src-a",
            [1.0 / math.sqrt(2.0) if i in (0, 1) else 0.0 for i in range(EMBEDDING_DIMENSION)],
        ),
    ]:
        service.ingest_document(
            db,
            title=title,
            source=source,
            content=content,
            provider=_static_provider(vector),
        )


class _static_provider:
    def __init__(self, vector):
        self.dimension = EMBEDDING_DIMENSION
        self._vector = vector

    def embed_texts(self, texts):
        return [list(self._vector) for _ in texts]


def test_threshold_filters_below_similarity(db):
    _seed(db)
    # No threshold: all three chunks (beta scores 0.0 but is still returned).
    assert len(service.retrieve_chunks(db, query_embedding=basis(0), top_k=10)) == 3
    # Threshold 0.5 keeps alpha (1.0) and gamma (~0.707), drops beta (0.0).
    results = service.retrieve_chunks(
        db, query_embedding=basis(0), top_k=10, min_similarity=0.5
    )
    assert [r.document_title for r in results] == ["alpha", "gamma"]
    # Threshold above gamma's score keeps only alpha.
    results = service.retrieve_chunks(
        db, query_embedding=basis(0), top_k=10, min_similarity=0.8
    )
    assert [r.document_title for r in results] == ["alpha"]
    # A query orthogonal to every stored chunk meets no threshold: zero
    # results — unrelated chunks are never silently returned.
    assert (
        service.retrieve_chunks(
            db, query_embedding=basis(5), top_k=10, min_similarity=0.1
        )
        == []
    )


def test_threshold_applies_before_top_k(db):
    _seed(db)
    # top_k=3 with a threshold only alpha passes → 1 result, not 3.
    results = service.retrieve_chunks(
        db, query_embedding=basis(0), top_k=3, min_similarity=0.9
    )
    assert [r.document_title for r in results] == ["alpha"]


def test_threshold_combines_with_filters(db):
    _seed(db)
    results = service.retrieve_chunks(
        db, query_embedding=basis(0), top_k=10, min_similarity=0.5, source="src-b"
    )
    assert results == []  # beta (src-b) is below the threshold


def test_threshold_validates_range(db):
    with pytest.raises(ValueError, match="min_similarity"):
        service.retrieve_chunks(db, query_embedding=basis(0), top_k=5, min_similarity=1.5)
    with pytest.raises(ValueError, match="min_similarity"):
        service.retrieve_chunks(db, query_embedding=basis(0), top_k=5, min_similarity=-2.0)


def test_retrieve_chunks_for_text_full_flow(db):
    _seed(db)
    provider = FixtureEmbeddingProvider(query_vector=basis(0))
    results = service.retrieve_chunks_for_text(
        db, query_text="coaching query about walking", provider=provider,
        top_k=2, min_similarity=0.5,
    )
    assert [r.document_title for r in results] == ["alpha", "gamma"]


def test_retrieve_chunks_for_text_validates_inputs(db):
    provider = FixtureEmbeddingProvider()
    with pytest.raises(ValueError, match="non-empty"):
        service.retrieve_chunks_for_text(db, query_text="   ", provider=provider)
    with pytest.raises(ValueError, match="dimension"):
        service.retrieve_chunks_for_text(
            db, query_text="q", provider=WrongDimensionProvider()
        )


def test_retrieve_chunks_for_text_on_empty_knowledge_base(db):
    provider = FixtureEmbeddingProvider()
    assert (
        service.retrieve_chunks_for_text(db, query_text="anything", provider=provider)
        == []
    )


# ─────────────────────────────────────────────────────────────────────────────
# API surface (min_similarity on POST /rag/retrieve)
# ─────────────────────────────────────────────────────────────────────────────


def test_retrieve_endpoint_applies_min_similarity(client, db):
    _seed(db)
    # No threshold → all three fixture chunks return.
    all_results = client.post(
        "/api/v1/rag/retrieve", json={"query_embedding": basis(0), "top_k": 10}
    ).json()["results"]
    assert len(all_results) == 3
    # Threshold 0.8 → only alpha (similarity 1.0).
    filtered = client.post(
        "/api/v1/rag/retrieve",
        json={"query_embedding": basis(0), "top_k": 10, "min_similarity": 0.8},
    ).json()["results"]
    assert [r["document_title"] for r in filtered] == ["alpha"]
    # Out-of-range threshold → 422, not a silent clamp.
    response = client.post(
        "/api/v1/rag/retrieve",
        json={"query_embedding": basis(0), "top_k": 5, "min_similarity": 2.0},
    )
    assert response.status_code == 422
