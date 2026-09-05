"""Phase 4C.2 coach tests: prompt builder + coach service.

All providers are fakes — zero API calls. The knowledge document is a
clearly-marked TEST FIXTURE, and the "embeddings" are geometric basis
vectors, not semantic ones.
"""
import uuid
from datetime import datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel

from app.api.dependencies import DEV_USER_ID
from app.core.database import engine
from app.modules.coach import service as coach_service
from app.modules.coach.llm import LLMProviderError
from app.modules.coach.prompt import build_coaching_prompt, build_retrieval_query
from app.modules.rag import service as rag_service
from app.modules.rag.constants import EMBEDDING_DIMENSION
from app.modules.rag.providers import EmbeddingProviderError
from app.modules.rag.schemas import RetrievedChunk
from app.modules.recommendations.schemas import FitnessContext
from app.modules.users.models import User

FIXTURE_CONTENT = (
    "TEST FIXTURE — placeholder coaching knowledge for coach tests. "
    "Not fitness or medical advice."
)

USER_ID = uuid.UUID(DEV_USER_ID)


def basis(index: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSION
    vector[index] = 1.0
    return vector


class FakeEmbeddingProvider:
    """TEST-ONLY: every text maps to basis(0) — so any query retrieves
    any fixture chunk with cosine similarity 1.0."""

    dimension = EMBEDDING_DIMENSION

    def embed_texts(self, texts):
        return [basis(0) for _ in texts]


class FailingEmbeddingProvider:
    dimension = EMBEDDING_DIMENSION

    def embed_texts(self, texts):
        raise EmbeddingProviderError("embedding exploded (test)")


class FakeLLM:
    """TEST-ONLY: records the prompt, returns a canned message."""

    def __init__(self, message="Small steady walks build the habit. Aim for your 1,000 steps today."):
        self.message = message
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.message


class FailingLLM:
    def generate(self, prompt: str) -> str:
        raise LLMProviderError("LLM exploded (test)")


def _context(**overrides) -> FitnessContext:
    defaults = dict(
        user_id=USER_ID,
        total_lifetime_steps=5000,
        hexes_owned=2,
        recent_captures_7d=1,
        last_capture_at=datetime.utcnow() - timedelta(days=1),
        total_defense_steps=300,
    )
    defaults.update(overrides)
    return FitnessContext(**defaults)


def _chunk(title="Walking basics", source="TEST-FIXTURE", similarity=0.9):
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title=title,
        document_source=source,
        chunk_index=0,
        content=FIXTURE_CONTENT,
        similarity=similarity,
        metadata={"topic": "walking"},
    )


@pytest.fixture()
def db():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


def _seed_user(db, steps=5000):
    db.add(User(id=USER_ID, username="devuser", total_lifetime_steps=steps))
    db.commit()


def _seed_knowledge(db):
    rag_service.ingest_document(
        db,
        title="Fixture walking knowledge",
        source="TEST-FIXTURE",
        content=FIXTURE_CONTENT,
        provider=FakeEmbeddingProvider(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Prompt builder
# ─────────────────────────────────────────────────────────────────────────────


def test_prompt_contains_real_context_and_recommendation():
    from app.modules.recommendations.service import recommend

    context = _context()
    recommendation = recommend(context)
    prompt = build_coaching_prompt(context, recommendation, [_chunk()])

    # Section 1: every real context signal is present with its value.
    assert "Total lifetime steps recorded: 5000" in prompt
    assert "Territory hexes currently owned: 2" in prompt
    assert "Hexes captured in the last 7 days: 1" in prompt
    assert "Total steps invested in territory defense: 300" in prompt
    assert "Last territory capture:" in prompt
    # The recommendation's goal is included.
    assert recommendation.title in prompt
    assert f"goal: {recommendation.target_value} {recommendation.target_metric}" in prompt


def test_prompt_contains_retrieved_knowledge_with_source():
    prompt = build_coaching_prompt(_context(), _recommend(), [_chunk()])
    assert "Retrieved fitness knowledge" in prompt
    assert "Walking basics" in prompt
    assert "TEST-FIXTURE" in prompt
    assert FIXTURE_CONTENT in prompt


def test_prompt_does_not_invent_unavailable_fields():
    prompt = build_coaching_prompt(_context(), _recommend(), [_chunk()])
    # XP, level, calories, distance, pace, heart-rate values do not exist
    # server-side — they must not appear as context facts. (The instruction
    # block's *prohibitions* may name these words, but no fabricated VALUE
    # may be stated; we assert no numeric calories/XP/level claims appear.)
    assert "level" not in prompt.lower()
    assert "XP" not in prompt
    assert "kcal" not in prompt
    # All numbers in the context section come from the real context:
    context_section = prompt.split("Retrieved fitness knowledge")[0]
    for number in ("5000", "2", "1", "300"):
        assert number in context_section


def _recommend():
    from app.modules.recommendations.service import recommend

    return recommend(_context())


def test_prompt_contains_grounding_and_safety_instructions():
    prompt = build_coaching_prompt(_context(), _recommend(), [_chunk()])
    assert "do NOT copy or echo" in prompt  # synthesize, don't echo
    assert "Do NOT invent user" in prompt  # (line-wrapped in the source)
    assert "medical advice" in prompt
    assert "qualified healthcare professional" in prompt
    assert "concise and actionable" in prompt
    assert "Do not reveal" in prompt  # no system-prompt leakage
    assert "information is limited" in prompt


def test_prompt_explicit_when_no_knowledge_retrieved():
    prompt = build_coaching_prompt(_context(), _recommend(), [])
    assert "NONE" in prompt
    assert "NO knowledge was retrieved" in prompt
    assert "safe, general fitness guidance only" in prompt


def test_retrieval_query_is_topical_and_uses_real_context():
    context = _context()
    query = build_retrieval_query(context, _recommend())
    assert "Coaching topic:" in query
    assert "5000" in query  # real lifetime steps
    assert "2 hexes owned" in query
    assert "1 captures in the last 7 days" in query


# ─────────────────────────────────────────────────────────────────────────────
# Coach service
# ─────────────────────────────────────────────────────────────────────────────


def test_happy_path_grounds_in_retrieved_knowledge(db):
    _seed_user(db, steps=5000)
    _seed_knowledge(db)
    llm = FakeLLM()

    result = coach_service.generate_coaching(
        db, user_id=USER_ID,
        embedding_provider=FakeEmbeddingProvider(), llm_provider=llm,
    )

    assert result.message == llm.message
    assert result.grounded is True
    assert result.context.total_lifetime_steps == 5000
    assert result.context.user_id == USER_ID
    assert result.recommendation.reason_code  # real Phase 4A engine output
    assert result.retrieval.retrieved_count == 1
    assert result.retrieval.chunks[0].document_source == "TEST-FIXTURE"
    assert result.retrieval.min_similarity == pytest.approx(
        coach_service.settings.rag_similarity_threshold
    )
    assert result.generated_at
    # The prompt the LLM saw contained the retrieved knowledge.
    assert FIXTURE_CONTENT in llm.prompts[0]


def test_empty_knowledge_base_returns_flagged_fallback(db):
    """Chosen fallback behavior (documented): retrieval found nothing →
    the coach still responds, but with grounded=False and a prompt that
    explicitly forbids citing knowledge."""
    _seed_user(db, steps=5000)
    llm = FakeLLM()

    result = coach_service.generate_coaching(
        db, user_id=USER_ID,
        embedding_provider=FakeEmbeddingProvider(), llm_provider=llm,
    )

    assert result.grounded is False
    assert result.retrieval.retrieved_count == 0
    assert "NO knowledge was retrieved" in llm.prompts[0]
    assert result.message  # still a useful, honest response


def test_below_threshold_retrieval_is_not_grounding(db):
    _seed_user(db, steps=5000)
    _seed_knowledge(db)

    # The query embedding is orthogonal to every stored chunk (cosine 0.0),
    # so nothing passes the default threshold — the response must be
    # flagged ungrounded, not padded with unrelated chunks.
    class OrthogonalProvider:
        dimension = EMBEDDING_DIMENSION

        def embed_texts(self, texts):
            return [basis(7) for _ in texts]

    result = coach_service.generate_coaching(
        db, user_id=USER_ID,
        embedding_provider=OrthogonalProvider(), llm_provider=FakeLLM(),
    )
    assert result.grounded is False
    assert result.retrieval.retrieved_count == 0


def test_embedding_failure_propagates(db):
    _seed_user(db, steps=5000)
    with pytest.raises(EmbeddingProviderError):
        coach_service.generate_coaching(
            db, user_id=USER_ID,
            embedding_provider=FailingEmbeddingProvider(), llm_provider=FakeLLM(),
        )


def test_retrieval_failure_propagates(db, monkeypatch):
    _seed_user(db, steps=5000)

    def boom(*args, **kwargs):
        raise RuntimeError("database exploded (test)")

    monkeypatch.setattr(coach_service, "retrieve_chunks", boom)
    with pytest.raises(RuntimeError, match="database exploded"):
        coach_service.generate_coaching(
            db, user_id=USER_ID,
            embedding_provider=FakeEmbeddingProvider(), llm_provider=FakeLLM(),
        )


def test_llm_failure_propagates(db):
    _seed_user(db, steps=5000)
    _seed_knowledge(db)
    with pytest.raises(LLMProviderError):
        coach_service.generate_coaching(
            db, user_id=USER_ID,
            embedding_provider=FakeEmbeddingProvider(), llm_provider=FailingLLM(),
        )


def test_empty_llm_message_is_rejected(db):
    _seed_user(db, steps=5000)
    with pytest.raises(coach_service.CoachValidationError, match="empty"):
        coach_service.generate_coaching(
            db, user_id=USER_ID,
            embedding_provider=FakeEmbeddingProvider(), llm_provider=FakeLLM(message="   "),
        )


def test_overlong_llm_message_is_rejected(db):
    _seed_user(db, steps=5000)
    with pytest.raises(coach_service.CoachValidationError, match="characters"):
        coach_service.generate_coaching(
            db, user_id=USER_ID,
            embedding_provider=FakeEmbeddingProvider(),
            llm_provider=FakeLLM(message="x" * (coach_service.MAX_MESSAGE_CHARS + 1)),
        )


def test_cold_start_user_still_gets_coaching(db):
    # No user row at all: build_fitness_context zeroes out and the rules
    # engine returns STARTER — the coach flow must work end to end.
    result = coach_service.generate_coaching(
        db, user_id=USER_ID,
        embedding_provider=FakeEmbeddingProvider(), llm_provider=FakeLLM(),
    )
    assert result.context.total_lifetime_steps == 0
    assert result.recommendation.reason_code == "COLD_START"
    assert result.message
