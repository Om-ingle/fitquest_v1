"""Phase 4C.2 coach API tests: GET /api/v1/coach.

Provider factories are monkeypatched with fakes — zero API calls. Every
upstream failure must surface as an honest HTTP error, never 200.
"""
import uuid

import pytest
from sqlmodel import Session, SQLModel

from app.api.dependencies import DEV_USER_ID
from app.core.database import engine
from app.modules.coach import router as coach_router
from app.modules.coach.llm import (
    LLMProviderError,
    LLMProviderNotConfigured,
    LLMProviderTimeout,
)
from app.modules.rag import service as rag_service
from app.modules.rag.constants import EMBEDDING_DIMENSION
from app.modules.rag.providers import (
    EmbeddingProviderNotConfigured,
    EmbeddingProviderTimeout,
)
from app.modules.users.models import User

USER_ID = uuid.UUID(DEV_USER_ID)
FIXTURE_CONTENT = "TEST FIXTURE — placeholder knowledge for the coach API tests."


def basis(index: int = 0) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSION
    vector[index] = 1.0
    return vector


class FakeEmbeddingProvider:
    dimension = EMBEDDING_DIMENSION

    def embed_texts(self, texts):
        return [basis(0) for _ in texts]


class FakeLLM:
    def __init__(self, message="Keep going — a short walk today covers your goal."):
        self.message = message

    def generate(self, prompt: str) -> str:
        return self.message


@pytest.fixture()
def db():
    # The client fixture (tests/conftest.py) already creates tables for
    # API tests; this fixture is for seeding data between calls.
    with Session(engine) as session:
        yield session


def _seed_user(session, steps=5000):
    session.add(User(id=USER_ID, username="devuser", total_lifetime_steps=steps))
    session.commit()


def _seed_knowledge(session):
    rag_service.ingest_document(
        session,
        title="Fixture knowledge",
        source="TEST-FIXTURE",
        content=FIXTURE_CONTENT,
        provider=FakeEmbeddingProvider(),
    )


def _patch_providers(monkeypatch, embedding=None, llm=None):
    monkeypatch.setattr(
        coach_router, "get_embedding_provider",
        lambda: embedding if embedding is not None else FakeEmbeddingProvider(),
    )
    monkeypatch.setattr(
        coach_router, "get_llm_provider",
        lambda: llm if llm is not None else FakeLLM(),
    )


def test_coach_endpoint_success(client, db, monkeypatch):
    _patch_providers(monkeypatch)
    _seed_user(db, steps=5000)
    _seed_knowledge(db)

    response = client.get("/api/v1/coach")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["message"].startswith("Keep going")
    assert body["grounded"] is True
    assert body["context"]["total_lifetime_steps"] == 5000
    assert body["context"]["user_id"] == DEV_USER_ID
    assert body["recommendation"]["reason_code"]
    assert body["generated_at"]
    retrieval = body["retrieval"]
    assert retrieval["retrieved_count"] == 1
    assert retrieval["chunks"][0]["document_source"] == "TEST-FIXTURE"
    assert "query_text" in retrieval and "min_similarity" in retrieval


def test_coach_endpoint_ungrounded_when_knowledge_base_empty(client, db, monkeypatch):
    _patch_providers(monkeypatch)
    _seed_user(db, steps=5000)

    body = client.get("/api/v1/coach").json()
    assert body["grounded"] is False
    assert body["retrieval"]["retrieved_count"] == 0
    assert body["message"]  # honest fallback response, still useful


def test_coach_endpoint_provider_not_configured_is_503(client, monkeypatch):
    def raise_not_configured():
        raise EmbeddingProviderNotConfigured("no key")

    monkeypatch.setattr(coach_router, "get_embedding_provider", raise_not_configured)
    response = client.get("/api/v1/coach")
    assert response.status_code == 503
    assert "no key" in response.json()["detail"]


def test_coach_endpoint_llm_not_configured_is_503(client, monkeypatch):
    def raise_not_configured():
        raise LLMProviderNotConfigured("no key")

    monkeypatch.setattr(coach_router, "get_embedding_provider", FakeEmbeddingProvider)
    monkeypatch.setattr(coach_router, "get_llm_provider", raise_not_configured)
    assert client.get("/api/v1/coach").status_code == 503


def test_coach_endpoint_embedding_timeout_is_504(client, monkeypatch):
    class TimeoutEmbedding:
        dimension = EMBEDDING_DIMENSION

        def embed_texts(self, texts):
            raise EmbeddingProviderTimeout("timed out")

    _patch_providers(monkeypatch, embedding=TimeoutEmbedding())
    assert client.get("/api/v1/coach").status_code == 504


def test_coach_endpoint_llm_timeout_is_504(client, monkeypatch):
    class TimeoutLLM:
        def generate(self, prompt):
            raise LLMProviderTimeout("timed out")

    _patch_providers(monkeypatch, llm=TimeoutLLM())
    assert client.get("/api/v1/coach").status_code == 504


def test_coach_endpoint_llm_error_is_502(client, monkeypatch):
    class ExplodingLLM:
        def generate(self, prompt):
            raise LLMProviderError("upstream 500")

    _patch_providers(monkeypatch, llm=ExplodingLLM())
    response = client.get("/api/v1/coach")
    assert response.status_code == 502
    assert "upstream 500" in response.json()["detail"]


def test_coach_endpoint_malformed_llm_response_is_502(client, monkeypatch):
    class EmptyLLM:
        def generate(self, prompt):
            return "   "  # empty after strip → validation failure

    _patch_providers(monkeypatch, llm=EmptyLLM())
    assert client.get("/api/v1/coach").status_code == 502


def test_coach_endpoint_never_leaks_the_prompt(client, db, monkeypatch):
    captured = {}

    class PromptRecordingLLM:
        def generate(self, prompt):
            captured["prompt"] = prompt
            return "Fine coaching message."

    _patch_providers(monkeypatch, llm=PromptRecordingLLM())
    _seed_user(db, steps=5000)

    body = client.get("/api/v1/coach").json()
    # The raw prompt (with its instructions) is internal — the response
    # exposes retrieval metadata, not the prompt itself.
    assert "Instructions:" not in body["message"]
    assert "prompt" not in body
    assert "You are FitQuest's AI fitness coach" not in body["message"]
    assert captured["prompt"]  # the LLM did receive one
