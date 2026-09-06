"""Phase 4C.3A context-scenario tests: the coach flow under all five
FitnessContext scenarios, using the REAL Phase 4A context/recommendation
machinery (build_fitness_context + recommend) wherever the database can
actually represent the scenario.

Providers are fakes — zero API calls. The knowledge document is a
clearly-marked TEST FIXTURE.

Scenario notes (honest limitation, documented in coach/README.md):
- COLD_START, LAPSED (RECOVERY), CONSISTENT (PROGRESS) and MAINTAIN are
  seeded through real User + HexOwnership rows, so build_fitness_context
  computes the context exactly as production would.
- TERRITORY_AT_RISK (DEFENSE) cannot be produced by build_fitness_context
  from stored data: it requires recent_captures_7d == 0 while
  last_capture_at is within 2 days, but any owned hex captured within the
  last 2 days necessarily also counts in the 7-day window. The scenario is
  therefore driven through recommend() with an explicitly constructed
  FitnessContext (the real rules engine, just not the real DB query).
"""
import uuid
from datetime import datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel

from app.api.dependencies import DEV_USER_ID
from app.core.database import engine
from app.modules.coach import service as coach_service
from app.modules.coach.llm import LLMProvider
from app.modules.coach.prompt import build_coaching_prompt, build_retrieval_query
from app.modules.map.models import HexOwnership
from app.modules.rag import service as rag_service
from app.modules.rag.constants import EMBEDDING_DIMENSION
from app.modules.rag.providers import EmbeddingProvider
from app.modules.recommendations.schemas import FitnessContext
from app.modules.recommendations.service import build_fitness_context, recommend
from app.modules.users.models import User

USER_ID = uuid.UUID(DEV_USER_ID)
FIXTURE_CONTENT = "TEST FIXTURE — placeholder scenario knowledge. Not advice."


def basis(index: int = 0) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSION
    vector[index] = 1.0
    return vector


class FakeEmbeddingProvider:
    """TEST-ONLY: every text → basis(0), so the seeded fixture chunk is
    always retrieved with cosine 1.0 (the scenario under test here is the
    CONTEXT, not the retrieval)."""

    dimension = EMBEDDING_DIMENSION

    def embed_texts(self, texts):
        return [basis(0) for _ in texts]


class PromptRecordingLLM:
    """TEST-ONLY LLMProvider: records every prompt, returns a fixed message."""

    def __init__(self, message="Steady, small walks keep the habit alive."):
        self.message = message
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.message


assert isinstance(PromptRecordingLLM(), LLMProvider)  # satisfies the protocol
assert isinstance(FakeEmbeddingProvider(), EmbeddingProvider)


@pytest.fixture()
def db():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        rag_service.ingest_document(
            session, title="Fixture scenario knowledge", source="TEST-FIXTURE",
            content=FIXTURE_CONTENT, provider=FakeEmbeddingProvider(),
        )
        yield session
    SQLModel.metadata.drop_all(engine)


def _seed_user(session, steps):
    session.add(User(id=USER_ID, username="devuser", total_lifetime_steps=steps))
    session.commit()


def _seed_hex(session, hex_id, days_ago, defense=100):
    session.add(
        HexOwnership(
            hex_id=hex_id,
            king_id=USER_ID,
            defense_score_steps=defense,
            captured_at=datetime.utcnow() - timedelta(days=days_ago),
        )
    )
    session.commit()


def _run(db):
    llm = PromptRecordingLLM()
    result = coach_service.generate_coaching(
        db, user_id=USER_ID,
        embedding_provider=FakeEmbeddingProvider(), llm_provider=llm,
    )
    return result, llm.prompts[0]


def _context_section(prompt: str) -> str:
    return prompt.split("Retrieved fitness knowledge")[0]


# ─────────────────────────────────────────────────────────────────────────────
# 1. Cold start — no user row, no territory
# ─────────────────────────────────────────────────────────────────────────────


def test_scenario_cold_start(db):
    result, prompt = _run(db)

    # The REAL context machinery zeroed out for a missing user row.
    assert result.context.total_lifetime_steps == 0
    assert result.context.hexes_owned == 0
    assert result.context.last_capture_at is None
    # The REAL rules engine chose STARTER.
    assert result.recommendation.reason_code == "COLD_START"
    assert result.recommendation.type == "STARTER"
    assert result.grounded is True  # fixture knowledge retrieved

    # The prompt states only the real (zero) values.
    section = _context_section(prompt)
    assert "Total lifetime steps recorded: 0" in section
    assert "Territory hexes currently owned: 0" in section
    assert "Last territory capture: never" in section
    # Nothing invented: no XP/level/calories/distance appear as values.
    assert "XP" not in prompt and "level" not in prompt.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Lapsed/recovery — history exists, last capture 5 days ago
# ─────────────────────────────────────────────────────────────────────────────


def test_scenario_lapsed_recovery(db):
    _seed_user(db, steps=8000)
    _seed_hex(db, "hex-lapsed-1", days_ago=5, defense=400)
    result, prompt = _run(db)

    assert result.context.total_lifetime_steps == 8000
    assert result.context.hexes_owned == 1
    assert result.context.recent_captures_7d == 1  # 5 days < 7-day window
    assert result.recommendation.reason_code == "LAPSED_PLAYER"
    assert result.recommendation.type == "RECOVERY"

    section = _context_section(prompt)
    assert "Total lifetime steps recorded: 8000" in section
    assert "Territory hexes currently owned: 1" in section
    assert result.recommendation.title in section
    # The retrieval query leans toward the return-after-break topic.
    query = result.retrieval.query_text
    assert "getting back to activity" in query


# ─────────────────────────────────────────────────────────────────────────────
# 3. Territory defense — R3 (see module docstring: not reachable via the DB
#    context builder, so the real recommend() engine is driven directly)
# ─────────────────────────────────────────────────────────────────────────────


def test_scenario_territory_defense(db):
    _seed_user(db, steps=12000)
    _seed_hex(db, "hex-defense-1", days_ago=1, defense=250)

    # Constructed context (impossible to seed via build_fitness_context —
    # see module docstring): owns 3 hexes, nothing captured this week, last
    # capture 36h ago.
    context = build_fitness_context(db, USER_ID).model_copy(
        update={"hexes_owned": 3, "recent_captures_7d": 0}
    )
    recommendation = recommend(context)  # the REAL rules engine
    assert recommendation.reason_code == "TERRITORY_AT_RISK"
    assert recommendation.type == "DEFENSE"

    # The coach layer receives it faithfully.
    prompt = build_coaching_prompt(context, recommendation, [])
    section = _context_section(prompt)
    assert recommendation.title in section
    assert "Territory hexes currently owned: 3" in section
    assert "Hexes captured in the last 7 days: 0" in section
    # The retrieval query leans toward the consistency/defense topic.
    assert "maintaining activity consistency" in build_retrieval_query(
        context, recommendation
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Consistent/progress — 4 captures this week
# ─────────────────────────────────────────────────────────────────────────────


def test_scenario_consistent_progress(db):
    _seed_user(db, steps=50000)
    for i in range(4):
        _seed_hex(db, f"hex-progress-{i}", days_ago=i, defense=300)
    result, prompt = _run(db)

    assert result.context.hexes_owned == 4
    assert result.context.recent_captures_7d == 4
    assert result.recommendation.reason_code == "CONSISTENT_PERFORMER"
    assert result.recommendation.type == "PROGRESS"

    section = _context_section(prompt)
    assert "Hexes captured in the last 7 days: 4" in section
    assert "Total steps invested in territory defense: 1200" in section
    # The retrieval query leans toward the progression topic.
    assert "gradual progression" in result.retrieval.query_text


# ─────────────────────────────────────────────────────────────────────────────
# 5. Maintain/default — active at a moderate volume
# ─────────────────────────────────────────────────────────────────────────────


def test_scenario_maintain_default(db):
    _seed_user(db, steps=20000)
    _seed_hex(db, "hex-maintain-1", days_ago=1, defense=150)
    result, prompt = _run(db)

    assert result.context.recent_captures_7d == 1
    assert result.recommendation.reason_code == "MAINTAIN"
    assert result.recommendation.type == "MAINTAIN"

    section = _context_section(prompt)
    assert "Total lifetime steps recorded: 20000" in section
    assert result.recommendation.title in section
    assert "consistent daily activity" in result.retrieval.query_text


# ─────────────────────────────────────────────────────────────────────────────
# Cross-scenario guarantees
# ─────────────────────────────────────────────────────────────────────────────


def test_recommendation_engine_stays_authoritative(db):
    """The coach result's recommendation is EXACTLY what the Phase 4A
    engine produces for the same context — the LLM layer never re-decides."""
    _seed_user(db, steps=8000)
    _seed_hex(db, "hex-auth-1", days_ago=5, defense=400)
    result, _prompt = _run(db)

    expected = recommend(build_fitness_context(db, USER_ID))
    assert result.recommendation == expected


def test_every_scenario_prompt_has_three_sections_and_no_invented_data(db):
    """Across scenarios the prompt always separates real context, retrieved
    knowledge, and instructions — and never carries invented user facts."""
    _seed_user(db, steps=8000)
    _seed_hex(db, "hex-sections-1", days_ago=1, defense=100)
    result, prompt = _run(db)

    assert "FitQuest user context" in prompt
    assert "Retrieved fitness knowledge" in prompt
    assert "Instructions:" in prompt
    assert prompt.index("FitQuest user context") < prompt.index(
        "Retrieved fitness knowledge"
    ) < prompt.index("Instructions:")
    # The context section contains ONLY the five real signals + the
    # recommendation; retrieved fixture text lives in the knowledge section.
    # (The INSTRUCTIONS block legitimately NAMES banned categories like
    # heart rate when forbidding them — so the ban list is checked against
    # the context section only.)
    assert FIXTURE_CONTENT not in _context_section(prompt)
    assert FIXTURE_CONTENT in prompt
    for banned in ("calories", "kcal", "heart rate", "km/h"):
        assert banned not in _context_section(prompt).lower()
