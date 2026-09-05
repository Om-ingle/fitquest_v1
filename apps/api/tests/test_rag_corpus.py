"""Phase 4C.2 curated-corpus tests.

The corpus is INGESTED here only with a deterministic fixture embedding
provider — no network, no real embeddings, nothing written to Supabase.
"""
import pytest
from sqlmodel import Session, SQLModel, select

from app.core.database import engine
from app.modules.rag import ingestion
from app.modules.rag.chunking import chunk_text
from app.modules.rag.constants import EMBEDDING_DIMENSION
from app.modules.rag.corpus import CORPUS
from app.modules.rag.models import RagChunk
from app.modules.rag.providers import EmbeddingProviderNotConfigured
from app.modules.rag.service import ingest_document, list_documents


class FixtureEmbeddingProvider:
    """Deterministic TEST-ONLY provider (geometric vectors, no network)."""

    dimension = EMBEDDING_DIMENSION
    model = "fixture-provider"

    def __init__(self):
        self.calls = 0

    def embed_texts(self, texts):
        self.calls += 1
        return [[0.1] * EMBEDDING_DIMENSION for _ in texts]


@pytest.fixture()
def db():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


# ─────────────────────────────────────────────────────────────────────────────
# Corpus invariants
# ─────────────────────────────────────────────────────────────────────────────


def test_corpus_is_small_and_well_formed():
    assert 3 <= len(CORPUS) <= 10  # deliberately small
    for document in CORPUS:
        assert document["title"].strip()
        assert document["source"].strip()
        assert document["content"].strip()
        assert document["metadata"].get("topic")
        assert document["metadata"]["kind"] == "curated_knowledge"
        assert document["source_url"].startswith("https://")


def test_corpus_sources_are_identified_and_trustworthy():
    assert {document["source"] for document in CORPUS} <= {"WHO", "CDC"}


def test_corpus_covers_the_coaching_topics():
    topics = {document["metadata"]["topic"] for document in CORPUS}
    assert {"activity-principles", "walking", "progression", "recovery", "consistency"} <= topics


def test_corpus_avoids_medical_advice():
    banned = ("diagnos", "medicat", "prescrib", "dosage", "cure")
    for document in CORPUS:
        text = (document["title"] + " " + document["content"]).lower()
        for term in banned:
            assert term not in text, f"banned term {term!r} in {document['title']!r}"


def test_corpus_is_distinct_from_test_fixtures():
    # The 4C.1 test fixture text must never appear in the curated corpus.
    for document in CORPUS:
        assert "TEST FIXTURE" not in document["content"]


def test_corpus_chunks_deterministically():
    for document in CORPUS:
        once = chunk_text(document["content"])
        assert once == chunk_text(document["content"])
        assert once  # every document produces at least one chunk


# ─────────────────────────────────────────────────────────────────────────────
# Ingestion behavior (fixture provider — no real embeddings, no network)
# ─────────────────────────────────────────────────────────────────────────────


def test_corpus_ingestion_is_deterministic_and_idempotent(db):
    provider = FixtureEmbeddingProvider()
    for document in CORPUS:
        ingest_document(
            db,
            title=document["title"],
            source=document["source"],
            content=document["content"],
            provider=provider,
            source_url=document["source_url"],
            document_metadata=document["metadata"],
        )
    first = {
        (d.title, d.chunk_count)
        for d in list_documents(db)
    }
    expected = {
        (document["title"], len(chunk_text(document["content"])))
        for document in CORPUS
    }
    assert first == expected

    # Re-ingest: same documents, same ids, chunks replaced not duplicated.
    for document in CORPUS:
        ingest_document(
            db,
            title=document["title"],
            source=document["source"],
            content=document["content"],
            provider=provider,
            source_url=document["source_url"],
            document_metadata=document["metadata"],
        )
    assert {(d.title, d.chunk_count) for d in list_documents(db)} == first


def test_corpus_metadata_is_preserved_on_chunks(db):
    provider = FixtureEmbeddingProvider()
    document = CORPUS[0]
    ingested = ingest_document(
        db,
        title=document["title"],
        source=document["source"],
        content=document["content"],
        provider=provider,
        source_url=document["source_url"],
        document_metadata=document["metadata"],
    )
    chunk = db.exec(
        select(RagChunk).where(RagChunk.document_id == ingested.id)
    ).first()
    assert chunk.meta == document["metadata"]
    assert chunk.embedding is not None


def test_ingestion_script_fails_without_provider_configuration(monkeypatch):
    # The CLI must refuse to run (loudly) without GEMINI_API_KEY — it can
    # never silently ingest without real embeddings.
    from app.core.config import settings

    monkeypatch.setattr(settings, "gemini_api_key", None)
    with pytest.raises(EmbeddingProviderNotConfigured):
        ingestion.main([])


def test_ingestion_script_dry_run_validates_corpus(monkeypatch, capsys):
    from app.core.config import settings

    monkeypatch.setattr(settings, "gemini_api_key", "dummy")
    monkeypatch.setattr(
        ingestion, "get_embedding_provider", lambda: FixtureEmbeddingProvider()
    )
    assert ingestion.main(["--dry-run"]) == 0
    assert "nothing written" in capsys.readouterr().out
