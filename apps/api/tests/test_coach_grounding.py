"""Phase 4C.3A grounding/safety tests for the existing coaching contract.

Focused additions on top of the 4C.2 suites (test_coach.py /
test_coach_api.py): section separation, fallback honesty, credential
hygiene, and the response schema contract. Providers are fakes — zero API
calls. No complicated safety framework, by scope.
"""
import uuid

import pytest
from sqlmodel import Session, SQLModel

from app.api.dependencies import DEV_USER_ID
from app.core.config import settings
from app.core.database import engine
from app.modules.coach import router as coach_router
from app.modules.coach import service as coach_service
from app.modules.coach.prompt import build_coaching_prompt
from app.modules.coach.schemas import CoachResponse
from app.modules.rag import service as rag_service
from app.modules.rag.constants import EMBEDDING_DIMENSION
from app.modules.recommendations.schemas import FitnessContext
from app.modules.users.models import User

USER_ID = uuid.UUID(DEV_USER_ID)
FIXTURE_CONTENT = "TEST FIXTURE — placeholder grounding knowledge. Not advice."


class FakeEmbeddingProvider:
    dimension = EMBEDDING_DIMENSION

    def embed_texts(self, texts):
        return [[1.0] + [0.0] * (EMBEDDING_DIMENSION - 1) for _ in texts]


class PromptRecordingLLM:
    def __init__(self, message="A short honest coaching message."):
        self.message = message
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.message


@pytest.fixture()
def db():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


def _context() -> FitnessContext:
    return FitnessContext(
        user_id=USER_ID,
        total_lifetime_steps=6000,
        hexes_owned=2,
        recent_captures_7d=1,
        last_capture_at=None,
        total_defense_steps=250,
    )


def _recommendation():
    from app.modules.recommendations.service import recommend

    return recommend(_context())


def _seed_fixture_knowledge(session):
    rag_service.ingest_document(
        session, title="Fixture grounding knowledge", source="TEST-FIXTURE",
        content=FIXTURE_CONTENT, provider=FakeEmbeddingProvider(),
    )


def _patch_providers(monkeypatch, llm):
    monkeypatch.setattr(coach_router, "get_embedding_provider", FakeEmbeddingProvider)
    monkeypatch.setattr(coach_router, "get_llm_provider", lambda: llm)


# ─────────────────────────────────────────────────────────────────────────────
# Grounding structure
# ─────────────────────────────────────────────────────────────────────────────


def test_grounded_prompt_never_carries_the_fallback_rule():
    """A response WITH retrieved knowledge must not also receive the
    no-knowledge fallback instructions — the two modes are exclusive."""
    from app.modules.rag.schemas import RetrievedChunk

    chunk = RetrievedChunk(
        chunk_id=uuid.uuid4(), document_id=uuid.uuid4(),
        document_title="Fixture doc", document_source="TEST-FIXTURE",
        chunk_index=0, content=FIXTURE_CONTENT, similarity=0.9,
    )
    fallback_prompt = build_coaching_prompt(_context(), _recommendation(), chunks=[])
    grounded_prompt = build_coaching_prompt(_context(), _recommendation(), chunks=[chunk])
    assert "NO knowledge was retrieved" in fallback_prompt
    assert "NO knowledge was retrieved" not in grounded_prompt


def test_fallback_prompt_references_no_documents_or_sources():
    """The no-knowledge fallback prompt must not mention any document
    title, source, or chunk — there is nothing to cite, and citing would
    make the fallback look like RAG."""
    from app.modules.rag.schemas import RetrievedChunk

    chunk = RetrievedChunk(
        chunk_id=uuid.uuid4(), document_id=uuid.uuid4(),
        document_title="Some Document", document_source="Some Source",
        chunk_index=0, content="some content", similarity=0.9,
    )
    fallback = build_coaching_prompt(_context(), _recommendation(), chunks=[])
    assert "Some Document" not in fallback
    assert "Some Source" not in fallback
    assert "(source:" not in fallback
    # The fallback explicitly forbids pretending knowledge exists. (The
    # rule line-wraps after "do NOT" in the prompt source, so assert the
    # contiguous part.)
    assert "reference any specific sources" in fallback


def test_context_and_knowledge_sections_are_labeled_and_distinct():
    """The prompt must keep user context and retrieved knowledge visibly
    separate so the model cannot mistake one for the other."""
    from app.modules.rag.schemas import RetrievedChunk

    chunk = RetrievedChunk(
        chunk_id=uuid.uuid4(), document_id=uuid.uuid4(),
        document_title="Fixture doc", document_source="TEST-FIXTURE",
        chunk_index=0, content=FIXTURE_CONTENT, similarity=0.9,
    )
    prompt = build_coaching_prompt(_context(), _recommendation(), [chunk])
    assert "FitQuest user context (all values are real backend data)" in prompt
    assert "Retrieved fitness knowledge" in prompt
    # The knowledge section carries the source attribution the context
    # section never uses, and vice versa: the context values (6000 steps,
    # 2 hexes) are not knowledge-chunk content.
    context_part = prompt.split("Retrieved fitness knowledge")[0]
    knowledge_part = prompt.split("Retrieved fitness knowledge")[1].split("Instructions")[0]
    assert "6000" in context_part and "6000" not in knowledge_part
    assert "TEST-FIXTURE" in knowledge_part and "TEST-FIXTURE" not in context_part


# ─────────────────────────────────────────────────────────────────────────────
# Credential hygiene
# ─────────────────────────────────────────────────────────────────────────────


def test_api_response_and_prompt_never_contain_the_api_key(client, db, monkeypatch):
    """Even with a real-looking key configured, neither the LLM prompt, the
    API response body, nor any error path may echo it."""
    sentinel = "AIza-sentinel-test-key-DO-NOT-PRINT"
    monkeypatch.setattr(settings, "gemini_api_key", sentinel)
    _seed_fixture_knowledge(db)
    db.add(User(id=USER_ID, username="devuser", total_lifetime_steps=6000))
    db.commit()
    llm = PromptRecordingLLM()
    _patch_providers(monkeypatch, llm)

    response = client.get("/api/v1/coach")

    assert response.status_code == 200, response.text
    assert sentinel not in response.text
    assert sentinel not in llm.prompts[0]
    # The key name itself never appears as a payload field either.
    assert "GEMINI_API_KEY" not in response.text


def test_error_response_does_not_leak_the_api_key(client, monkeypatch):
    sentinel = "AIza-sentinel-test-key-DO-NOT-PRINT"
    monkeypatch.setattr(settings, "gemini_api_key", sentinel)

    class ExplodingEmbedding:
        dimension = EMBEDDING_DIMENSION

        def embed_texts(self, texts):
            from app.modules.rag.providers import EmbeddingProviderError

            raise EmbeddingProviderError("upstream request failed")

    monkeypatch.setattr(coach_router, "get_embedding_provider", ExplodingEmbedding)
    monkeypatch.setattr(
        coach_router, "get_llm_provider", lambda: PromptRecordingLLM()
    )

    response = client.get("/api/v1/coach")
    assert response.status_code == 502
    assert sentinel not in response.text


# ─────────────────────────────────────────────────────────────────────────────
# Response schema contract (4C.3A section E — inspected, asserted explicitly)
# ─────────────────────────────────────────────────────────────────────────────


def test_coach_response_contract_fields_are_exactly_this_set():
    """The wire contract is intentionally small: message, grounded flag,
    generation time, the real context, the recommendation, retrieval
    metadata, and the Fix E audit fields (context fingerprint + cached
    flag). Nothing else (no prompt, no provider details)."""
    assert set(CoachResponse.model_fields) == {
        "generated_at", "message", "grounded", "context", "recommendation",
        "retrieval", "context_fingerprint", "cached",
    }
    from app.modules.coach.schemas import RetrievalInfo

    assert set(RetrievalInfo.model_fields) == {
        "query_text", "top_k", "min_similarity", "retrieved_count", "chunks",
    }


def test_service_strips_whitespace_from_the_llm_message(db):
    """Whitespace-only padding around an otherwise valid message is not
    part of the coaching output."""
    db.add(User(id=USER_ID, username="devuser", total_lifetime_steps=6000))
    db.commit()
    _seed_fixture_knowledge(db)
    llm = PromptRecordingLLM(message="  \n A real coaching message. \n\t")

    result = coach_service.generate_coaching(
        db, user_id=USER_ID,
        embedding_provider=FakeEmbeddingProvider(), llm_provider=llm,
    )
    assert result.message == "A real coaching message."


def test_grounded_flag_reflects_retrieval_not_the_message(db):
    """`grounded` is decided by whether chunks were retrieved — never by
    inspecting the (untrusted) LLM text."""
    db.add(User(id=USER_ID, username="devuser", total_lifetime_steps=6000))
    db.commit()
    # No knowledge seeded → nothing retrieved.
    result = coach_service.generate_coaching(
        db, user_id=USER_ID,
        embedding_provider=FakeEmbeddingProvider(),
        llm_provider=PromptRecordingLLM(),
    )
    assert result.retrieval.retrieved_count == 0
    assert result.grounded is False
