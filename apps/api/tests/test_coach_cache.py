"""Fix E backend tests: coach context fingerprint + per-user caching.

Covers the spec's cache behaviours (Fix E part 5, backend):
  1. same user + same fingerprint → cached, LLM NOT called again
  2. changed context (steps / new daily activity) → miss, LLM called, new
     response stored
  3. different users → isolation (a cached generation for A is never served
     to B)
  4. failures are never cached → a Retry after an error still reaches the LLM
  5. RAG retrieval still works and `grounded` stays correct on cached hits

Providers are fakes — zero external LLM/embedding calls.
"""
import datetime as dt
import uuid

import pytest
from sqlmodel import Session, SQLModel

from app.api.dependencies import DEV_USER_ID
from app.core.database import engine
from app.modules.coach import router as coach_router
from app.modules.coach import service as coach_service
from app.modules.coach.cache import CoachCache, context_fingerprint
from app.modules.rag import service as rag_service
from app.modules.rag.constants import EMBEDDING_DIMENSION
from app.modules.recommendations.schemas import FitnessContext
from app.modules.recommendations.service import build_fitness_context
from app.modules.runs.models import UserDailyActivity
from app.modules.users.models import User

USER_ID = uuid.UUID(DEV_USER_ID)
OTHER_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
FIXTURE_CONTENT = "Fix E cache fixture — placeholder grounding knowledge. Not advice."
TODAY = dt.date.today()


class FakeEmbeddingProvider:
    dimension = EMBEDDING_DIMENSION

    def embed_texts(self, texts):
        return [[1.0] + [0.0] * (EMBEDDING_DIMENSION - 1) for _ in texts]


class PromptRecordingLLM:
    """Fake LLM that counts calls and records every prompt it is given."""

    def __init__(self, message="A short honest coaching message."):
        self.message = message
        self.call_count = 0
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.call_count += 1
        self.prompts.append(prompt)
        return self.message


class EmptyLLM:
    def generate(self, prompt: str) -> str:
        return ""


@pytest.fixture()
def db():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _seed_user(session, user_id: uuid.UUID, steps: int = 0) -> None:
    session.add(
        User(id=user_id, username=f"user-{user_id.hex[-12:]}",
             total_lifetime_steps=steps)
    )
    session.commit()


def _seed_knowledge(session) -> None:
    rag_service.ingest_document(
        session, title="Fix E cache fixture", source="TEST-FIXTURE",
        content=FIXTURE_CONTENT, provider=FakeEmbeddingProvider(),
    )


def _seed_daily(
    session,
    user_id: uuid.UUID,
    *,
    activity_date: dt.date,
    steps: int,
    active_minutes: int = 30,
    goal_steps: int | None = None,
    goal_completed: bool | None = None,
) -> None:
    session.add(
        UserDailyActivity(
            user_id=user_id,
            activity_date=activity_date,
            steps=steps,
            active_minutes=active_minutes,
            goal_steps=goal_steps,
            goal_completed=goal_completed,
        )
    )
    session.commit()


def _update_lifetime_steps(session, user_id: uuid.UUID, steps: int) -> None:
    user = session.get(User, user_id)
    user.total_lifetime_steps = steps
    session.add(user)
    session.commit()


def _generate(session, user_id, llm, cache: CoachCache | None):
    return coach_service.generate_coaching(
        session, user_id=user_id,
        embedding_provider=FakeEmbeddingProvider(), llm_provider=llm,
        cache=cache,
    )


def _patch_providers(monkeypatch, llm):
    monkeypatch.setattr(coach_router, "get_embedding_provider", FakeEmbeddingProvider)
    monkeypatch.setattr(coach_router, "get_llm_provider", lambda: llm)


# ─────────────────────────────────────────────────────────────────────────────
# Fingerprint unit behaviour
# ─────────────────────────────────────────────────────────────────────────────


def _ctx(**overrides) -> FitnessContext:
    defaults = dict(
        user_id=USER_ID, total_lifetime_steps=6000, hexes_owned=2,
        recent_captures_7d=1, last_capture_at=None, total_defense_steps=250,
    )
    defaults.update(overrides)
    return FitnessContext(**defaults)


def test_fingerprint_is_deterministic_and_sensitive():
    equal = _ctx()
    assert context_fingerprint(equal) == context_fingerprint(_ctx())
    # Any single context value flips the digest.
    assert context_fingerprint(_ctx()) != context_fingerprint(_ctx(total_lifetime_steps=6001))
    assert context_fingerprint(_ctx()) != context_fingerprint(_ctx(user_id=OTHER_USER_ID))
    # New daily-activity fields participate too.
    assert context_fingerprint(_ctx()) != context_fingerprint(
        _ctx(activity_date=TODAY, steps_today=3500, active_minutes_today=40,
             goal_steps=5000, goal_completed_today=False, goal_progress_ratio=0.7)
    )


def test_context_exposes_latest_daily_activity_from_db(db):
    """build_fitness_context surfaces the latest reported activity day, and
    nothing is fabricated when the user has reported none."""
    _seed_user(db, USER_ID, steps=6000)
    context = build_fitness_context(db, USER_ID)
    assert context.activity_date is None
    assert context.steps_today is None
    assert context.goal_progress_ratio is None

    _seed_daily(db, USER_ID, activity_date=TODAY, steps=3500, active_minutes=40,
                goal_steps=5000, goal_completed=False)
    context = build_fitness_context(db, USER_ID)
    assert context.activity_date == TODAY
    assert context.steps_today == 3500
    assert context.active_minutes_today == 40
    assert context.goal_steps == 5000
    assert context.goal_completed_today is False
    assert context.goal_progress_ratio == pytest.approx(0.7)

    # An older report is the "latest" only when nothing newer exists — the
    # newest row wins (not "today" arithmetic).
    yesterday = TODAY - dt.timedelta(days=1)
    _seed_daily(db, USER_ID, activity_date=yesterday, steps=999,
                active_minutes=10, goal_steps=8000)
    context = build_fitness_context(db, USER_ID)
    assert context.activity_date == TODAY
    assert context.steps_today == 3500


# ─────────────────────────────────────────────────────────────────────────────
# Cache behaviour (service level, fresh CoachCache per test)
# ─────────────────────────────────────────────────────────────────────────────


def test_same_context_served_from_cache_llm_not_called_again(db):
    _seed_user(db, USER_ID, steps=6000)
    _seed_knowledge(db)
    llm = PromptRecordingLLM()
    cache = CoachCache()

    first = _generate(db, USER_ID, llm, cache)
    assert llm.call_count == 1
    assert first.cached is False
    assert first.grounded is True            # RAG retrieval worked
    assert first.retrieval.retrieved_count >= 1

    second = _generate(db, USER_ID, llm, cache)
    assert llm.call_count == 1               # NOT called a second time
    assert second.cached is True
    assert second.context_fingerprint == first.context_fingerprint
    assert second.message == first.message
    assert second.grounded is True           # cached response keeps its flag


def test_changed_lifetime_steps_is_a_cache_miss_and_regenerates(db):
    _seed_user(db, USER_ID, steps=6000)
    _seed_knowledge(db)
    llm = PromptRecordingLLM()
    cache = CoachCache()

    first = _generate(db, USER_ID, llm, cache)
    _update_lifetime_steps(db, USER_ID, 7000)

    second = _generate(db, USER_ID, llm, cache)
    assert llm.call_count == 2
    assert second.cached is False
    assert second.context_fingerprint != first.context_fingerprint
    assert second.context.total_lifetime_steps == 7000


def test_new_daily_activity_is_a_cache_miss_then_reused(db):
    _seed_user(db, USER_ID, steps=6000)
    _seed_knowledge(db)
    llm = PromptRecordingLLM()
    cache = CoachCache()

    first = _generate(db, USER_ID, llm, cache)
    assert first.context.steps_today is None

    _seed_daily(db, USER_ID, activity_date=TODAY, steps=3500, active_minutes=40,
                goal_steps=5000, goal_completed=False)
    second = _generate(db, USER_ID, llm, cache)
    assert llm.call_count == 2
    assert second.cached is False
    assert second.context.steps_today == 3500
    assert second.context_fingerprint != first.context_fingerprint

    third = _generate(db, USER_ID, llm, cache)
    assert llm.call_count == 2               # now stable again
    assert third.cached is True


def test_cache_is_scoped_per_user(db):
    _seed_user(db, USER_ID, steps=6000)
    _seed_user(db, OTHER_USER_ID, steps=6000)   # identical stats on purpose
    _seed_knowledge(db)
    llm = PromptRecordingLLM()
    cache = CoachCache()

    a1 = _generate(db, USER_ID, llm, cache)
    b1 = _generate(db, OTHER_USER_ID, llm, cache)   # must NOT hit A's entry
    assert llm.call_count == 2
    assert b1.cached is False

    a2 = _generate(db, USER_ID, llm, cache)         # A served from cache
    b2 = _generate(db, OTHER_USER_ID, llm, cache)   # B served from cache
    assert llm.call_count == 2
    assert a2.cached is True and b2.cached is True
    assert a2.context.user_id == USER_ID
    assert b2.context.user_id == OTHER_USER_ID
    assert a2.context_fingerprint != b2.context_fingerprint


def test_failed_generation_is_never_cached(db):
    """An LLM that fails validation must leave no entry — so a Retry after a
    failure still runs the full pipeline (spec: failures never cached)."""
    _seed_user(db, USER_ID, steps=6000)
    _seed_knowledge(db)
    cache = CoachCache()

    with pytest.raises(coach_service.CoachValidationError):
        _generate(db, USER_ID, EmptyLLM(), cache)
    current = build_fitness_context(db, USER_ID)
    assert cache.get_cached(USER_ID, context_fingerprint(current)) is None

    llm = PromptRecordingLLM()
    ok = _generate(db, USER_ID, llm, cache)
    assert ok.cached is False
    assert llm.call_count == 1


def test_no_cache_argument_never_serves_stale(db):
    """Direct-service callers that pass no cache keep the old semantics:
    every call reaches the LLM (existing suites depend on this)."""
    _seed_user(db, USER_ID, steps=6000)
    _seed_knowledge(db)
    llm = PromptRecordingLLM()
    _generate(db, USER_ID, llm, None)
    _generate(db, USER_ID, llm, None)
    assert llm.call_count == 2


# ─────────────────────────────────────────────────────────────────────────────
# HTTP endpoint: real router + module singleton (spec: no 2nd LLM on repeat)
# ─────────────────────────────────────────────────────────────────────────────


def test_endpoint_serves_cached_on_repeat_request(client, db, monkeypatch):
    _seed_user(db, USER_ID, steps=6000)
    _seed_knowledge(db)
    llm = PromptRecordingLLM()
    _patch_providers(monkeypatch, llm)

    first = client.get("/api/v1/coach")
    assert first.status_code == 200, first.text
    body1 = first.json()

    second = client.get("/api/v1/coach")
    assert second.status_code == 200, second.text
    body2 = second.json()

    assert llm.call_count == 1               # repeated GET → no 2nd LLM
    assert body1["cached"] is False
    assert body2["cached"] is True
    assert body1["context_fingerprint"] == body2["context_fingerprint"]
    assert body1["message"] == body2["message"]


def test_endpoint_regenerates_when_activity_changes(client, db, monkeypatch):
    _seed_user(db, USER_ID, steps=6000)
    _seed_knowledge(db)
    llm = PromptRecordingLLM()
    _patch_providers(monkeypatch, llm)

    body1 = client.get("/api/v1/coach").json()

    # A fresh device sync lands new daily telemetry (as POST /runs/sync does).
    _seed_daily(db, USER_ID, activity_date=TODAY, steps=4100, active_minutes=55,
                goal_steps=5000, goal_completed=False)

    body2 = client.get("/api/v1/coach").json()
    assert llm.call_count == 2
    assert body2["cached"] is False
    assert body2["context_fingerprint"] != body1["context_fingerprint"]
    assert body2["context"]["steps_today"] == 4100

    body3 = client.get("/api/v1/coach").json()
    assert llm.call_count == 2
    assert body3["cached"] is True
