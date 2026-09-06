"""M8.3A — trigger -> AI coaching -> WebSocket push tests.

Covers the full push stage added by M8.3A:

    real trigger -> (M8.3A PushCoach) -> existing grounded-AI stack
        -> CoachResponse -> coaching_message over the existing M8.2 transport

Policy under test, per the M8.3A spec:
  * each real trigger type produces a ``coaching_message`` envelope whose
    prompt says WHY it fired (run / territory / milestone), reusing the
    existing CoachResponse schema — nothing invented;
  * the producer never waits for the LLM (handle_trigger only schedules);
  * a burst (several triggers back-to-back) coalesces into ONE generation;
  * a push within the post-push cooldown window is suppressed;
  * identical (context, reason) is deduped via the existing CoachCache under
    a reason-aware push key — no second LLM call;
  * a changed context (or a changed reason on the same context) regenerates;
  * users are isolated (per-user armed/cooldown/cache);
  * no live session -> no paid generation at all;
  * an LLM/RAG failure is contained, delivers NO fake message, and does not
    break later triggers; a broken WS client likewise never breaks the
    generation or the producer;
  * GET /api/v1/coach (the pull service path) is unchanged — its prompt
    carries no event_context.

The final integration test runs the REAL engine path (process_run_sync ->
module trigger_engine) into a REAL WebSocket session over the TestClient and
asserts the client receives the raw M8.2 ``coaching_trigger`` then an M8.3A
``coaching_message``. Providers are fakes end-to-end — zero API calls.
"""
import json
import uuid

import pytest
from sqlmodel import Session, SQLModel

from app.api.dependencies import DEV_USER_ID
from app.core.database import engine
from app.modules.coach import service as coach_service
from app.modules.coach.cache import CoachCache
from app.modules.coach.llm import LLMProviderError
from app.modules.coach.push import (
    COACHING_MESSAGE_TYPE,
    describe_event_context,
    push_coach,
    push_generation_key,
)
from app.modules.rag import service as rag_service
from app.modules.rag.constants import EMBEDDING_DIMENSION
from app.modules.runs.schemas import RunSyncPayload
from app.modules.runs.service import process_run_sync
from app.modules.triggers import ws as ws_module
from app.modules.triggers.engine import (
    CoachingTrigger,
    TriggerType,
    trigger_engine,
)
from app.modules.users.models import User

USER_ID = DEV_USER_ID
USER_A = USER_ID
USER_B = "00000000-0000-0000-0000-0000000000b2"
USER_C = "00000000-0000-0000-0000-0000000000c3"
WS_PATH = "/api/v1/ws/coaching"
FIXTURE_CONTENT = "TEST FIXTURE — M8.3A push scenario knowledge. Not advice."


def _ws_url(user_id=None):
    return WS_PATH if user_id is None else f"{WS_PATH}?user_id={user_id}"


class _Connect:
    """``client.websocket_connect`` tolerant of Starlette's CancelledError
    teardown quirk (same wrapper as the M8.2 tests)."""

    def __init__(self, client, user_id=None):
        self._inner = client.websocket_connect(_ws_url(user_id))

    def __enter__(self):
        return self._inner.__enter__()

    def __exit__(self, et, ev, tb):
        from concurrent import futures

        try:
            return self._inner.__exit__(et, ev, tb)
        except futures.CancelledError:
            return et is None


# ─────────────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────────────


def _basis(index=0):
    vector = [0.0] * EMBEDDING_DIMENSION
    vector[index] = 1.0
    return vector


class FakeEmbeddingProvider:
    """TEST-ONLY: every text -> basis(0), so a seeded fixture chunk retrieves
    with cosine 1.0 when present and nothing is retrieved when absent."""

    dimension = EMBEDDING_DIMENSION

    def embed_texts(self, texts):
        return [_basis(0) for _ in texts]


class PromptRecordingLLM:
    """TEST-ONLY LLMProvider: records every prompt, returns a fixed message."""

    def __init__(self, message="Steady, small walks keep the habit alive."):
        self.message = message
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return self.message


class FlakyLLM:
    """TEST-ONLY: fails on the first call, works afterwards. Counts calls."""

    def __init__(self):
        self.calls = 0
        self.prompts = []

    def generate(self, prompt):
        self.calls += 1
        self.prompts.append(prompt)
        if self.calls == 1:
            raise LLMProviderError("LLM exploded (test)")
        return "Recovered after the transient failure."


class JobRecorder:
    """TEST-ONLY ``schedule``: captures jobs without running them, so tests
    decide exactly when the background generation executes (deterministic)."""

    def __init__(self):
        self.jobs = []

    def __call__(self, fn):
        self.jobs.append(fn)

    def run_all(self):
        while self.jobs:
            self.jobs.pop(0)()


class FakeTransport:
    """TEST-ONLY stand-in for the M8.2 CoachingSessionManager: a set of "live"
    users and a record of every delivered envelope."""

    def __init__(self, *live):
        self.live = set(live)
        self.sent = []  # (user_id, envelope_json_string)

    def has_live_sessions(self, user_id):
        return user_id in self.live

    def send_to_user(self, user_id, envelope):
        self.sent.append((user_id, envelope))


class ExplodingTransport(FakeTransport):
    """TEST-ONLY: a live user whose delivery always fails (broken socket)."""

    def send_to_user(self, user_id, envelope):
        super().send_to_user(user_id, envelope)
        raise ConnectionError("broken pipe (test)")


class FakeClock:
    def __init__(self, start=0.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def tables():
    # drop-first: a timeout-killed run can leave rows behind in the shared
    # test_fitquest.db file; recreate from scratch so this test is clean.
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    yield
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def _guard_push_singleton():
    """Snapshot + restore the process-global PushCoach config so no test
    leaks enabled/fakes/caches into the next one (M8.1/M8.2 rely on it being
    disabled in the conftest client fixture)."""
    pc = push_coach
    saved = {
        attr: getattr(pc, attr)
        for attr in (
            "enabled", "ws", "cache", "schedule", "now", "cooldown_seconds",
            "session_factory", "embedding_factory", "llm_factory",
        )
    }
    pc.reset()
    yield pc
    pc.reset()
    for attr, value in saved.items():
        setattr(pc, attr, value)


def _config(pc, *, live=(), llm=None, embedding=None, cooldown=30.0,
            clock=None, cache=None, schedule=None, transport=None):
    """Enable push_coach and point every seam at test doubles."""
    pc.enabled = True
    pc.ws = transport if transport is not None else FakeTransport(*live)
    pc.cache = cache if cache is not None else CoachCache()
    pc.session_factory = lambda: Session(engine)
    pc.embedding_factory = (
        (lambda: embedding) if embedding is not None
        else (lambda: FakeEmbeddingProvider())
    )
    assert llm is not None, "push tests always inject an LLM double"
    pc.llm_factory = lambda: llm
    pc.cooldown_seconds = cooldown
    pc.now = clock if clock is not None else FakeClock()
    rec = schedule if schedule is not None else JobRecorder()
    pc.schedule = rec
    return pc.ws, rec, llm


def _trigger(kind, uid=USER_ID, dedupe="k", event_id=None):
    return CoachingTrigger(
        trigger_type=kind,
        user_id=uuid.UUID(uid),
        dedupe_key=dedupe,
        event_id=event_id,
    )


def _seed_user(steps=0, user_id=USER_ID):
    # Upsert by primary key so a row left by an interrupted run cannot collide.
    with Session(engine) as session:
        existing = session.get(User, uuid.UUID(user_id))
        if existing is None:
            session.add(
                User(
                    id=uuid.UUID(user_id),
                    username=f"user-{user_id}",
                    total_lifetime_steps=steps,
                )
            )
        else:
            existing.total_lifetime_steps = steps
        session.commit()


def _set_lifetime_steps(steps, user_id=USER_ID):
    with Session(engine) as session:
        user = session.get(User, uuid.UUID(user_id))
        assert user is not None
        user.total_lifetime_steps = steps
        session.commit()


def _ingest_knowledge():
    with Session(engine) as session:
        rag_service.ingest_document(
            session,
            title="Fixture push knowledge",
            source="TEST-FIXTURE",
            content=FIXTURE_CONTENT,
            provider=FakeEmbeddingProvider(),
        )


def _delivered_message(transport):
    """Decode the latest delivered coaching_message envelope as a dict."""
    assert transport.sent, "no envelope was delivered"
    return json.loads(transport.sent[-1][1])


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers: event phrasing, composite cache key
# ─────────────────────────────────────────────────────────────────────────────


def test_describe_event_context_maps_each_real_trigger_type():
    assert (
        describe_event_context((TriggerType.WORKOUT_COMPLETED,))
        == "the user completed a run"
    )
    assert (
        describe_event_context((TriggerType.TERRITORY_CAPTURED,))
        == "the user captured new territory"
    )
    assert (
        describe_event_context((TriggerType.ACTIVITY_MILESTONE,))
        == "the user reached a daily step milestone"
    )
    # Empty / unknown reasons produce no fabricated explanation.
    assert describe_event_context(()) == ""


def test_push_cache_key_is_reason_aware_order_free_and_prefix_isolated():
    user = uuid.UUID(USER_A)
    fp = "plain-fingerprint"
    k_workout = push_generation_key(user, fp, (TriggerType.WORKOUT_COMPLETED,))
    k_workout2 = push_generation_key(user, fp, (TriggerType.WORKOUT_COMPLETED,))
    k_territory = push_generation_key(user, fp, (TriggerType.TERRITORY_CAPTURED,))
    assert k_workout == k_workout2
    assert k_workout != k_territory  # same context, different reason -> distinct
    # Reason order never matters (deterministic key).
    assert push_generation_key(
        user, fp, (TriggerType.TERRITORY_CAPTURED, TriggerType.WORKOUT_COMPLETED)
    ) == push_generation_key(
        user, fp, (TriggerType.WORKOUT_COMPLETED, TriggerType.TERRITORY_CAPTURED)
    )
    # A push key can never equal a plain fingerprint (prefix isolation), so
    # push and pull entries coexist in the same CoachCache without colliding.
    assert k_workout.startswith("push:")
    assert k_workout != fp


# ─────────────────────────────────────────────────────────────────────────────
# Each real trigger type produces a coaching_message
# ─────────────────────────────────────────────────────────────────────────────


def test_each_trigger_type_produces_coaching_message_with_reason_aware_prompt(tables):
    transport, recorder, llm = _config(
        push_coach, live=(USER_A, USER_B, USER_C), llm=PromptRecordingLLM(),
        cooldown=0.0,
    )
    prompt_phrase = {
        TriggerType.WORKOUT_COMPLETED: "completed a run",
        TriggerType.TERRITORY_CAPTURED: "captured new territory",
        TriggerType.ACTIVITY_MILESTONE: "reached a daily step milestone",
    }

    for i, kind in enumerate(
        (TriggerType.WORKOUT_COMPLETED,
         TriggerType.TERRITORY_CAPTURED,
         TriggerType.ACTIVITY_MILESTONE)
    ):
        uid = (USER_A, USER_B, USER_C)[i]
        push_coach.handle_trigger(_trigger(kind, uid, dedupe=f"dedupe-{kind.value}"))
        assert len(recorder.jobs) == 1  # scheduled, not yet run
        recorder.run_all()

        # Exactly one new delivery, to the right user, real envelope shape.
        assert len(transport.sent) == i + 1
        dest, _raw = transport.sent[-1]
        assert dest == uid
        data = _delivered_message(transport)
        assert set(data.keys()) == {"type", "trigger", "coach"}  # nothing invented
        assert data["type"] == COACHING_MESSAGE_TYPE == "coaching_message"
        assert data["trigger"]["trigger_type"] == kind.value
        assert data["trigger"]["user_id"] == uid
        # Coach carries the REAL CoachResponse fields.
        coach = data["coach"]
        assert coach["message"]
        assert "context_fingerprint" in coach
        assert "recommendation" in coach and "context" in coach
        # The LLM saw WHY this message was generated (distinguishes the types).
        assert prompt_phrase[kind] in llm.prompts[-1]


# ─────────────────────────────────────────────────────────────────────────────
# Producer is never blocked by the LLM
# ─────────────────────────────────────────────────────────────────────────────


def test_handle_trigger_returns_immediately_and_never_calls_the_llm():
    # No DB tables needed: the job is only scheduled, never executed here.
    llm = PromptRecordingLLM()
    transport, recorder, _ = _config(push_coach, live=(USER_A,), llm=llm)

    push_coach.handle_trigger(_trigger(TriggerType.WORKOUT_COMPLETED, dedupe="k-1"))

    assert len(recorder.jobs) == 1  # the producer handed off and returned
    assert llm.prompts == []  # nothing ran synchronously inside handle_trigger
    assert transport.sent == []


def test_no_live_session_means_no_paid_generation_at_all():
    llm = PromptRecordingLLM()
    transport, recorder, _ = _config(push_coach, live=(), llm=llm)

    push_coach.handle_trigger(_trigger(TriggerType.WORKOUT_COMPLETED, dedupe="k-1"))

    assert recorder.jobs == []  # never even scheduled
    assert llm.prompts == []
    assert transport.sent == []


# ─────────────────────────────────────────────────────────────────────────────
# Coalescing / cooldown
# ─────────────────────────────────────────────────────────────────────────────


def test_rapid_burst_coalesces_into_one_generation(tables):
    transport, recorder, llm = _config(push_coach, live=(USER_A,),
                                       llm=PromptRecordingLLM(),
                                       cooldown=30.0)
    # A run that also captures territory and crosses a milestone fires three
    # triggers back-to-back while the first generation is armed.
    push_coach.handle_trigger(
        _trigger(TriggerType.WORKOUT_COMPLETED, dedupe="r-1", event_id="run-1")
    )
    push_coach.handle_trigger(_trigger(TriggerType.TERRITORY_CAPTURED, dedupe="h-1"))
    push_coach.handle_trigger(_trigger(TriggerType.ACTIVITY_MILESTONE, dedupe="m-1"))

    assert len(recorder.jobs) == 1  # one generation for the whole burst
    recorder.run_all()

    assert len(llm.prompts) == 1
    assert len(transport.sent) == 1
    # The single generation saw ALL three reasons folded in.
    assert "completed a run" in llm.prompts[0]
    assert "captured new territory" in llm.prompts[0]
    assert "reached a daily step milestone" in llm.prompts[0]
    # The envelope's representative trigger is the one that armed the push.
    assert _delivered_message(transport)["trigger"]["event_id"] == "run-1"


def test_trigger_inside_post_push_cooldown_is_suppressed(tables):
    clock = FakeClock()
    transport, recorder, llm = _config(push_coach, live=(USER_A,),
                                       llm=PromptRecordingLLM(),
                                       cooldown=30.0,
                                       clock=clock)
    push_coach.handle_trigger(
        _trigger(TriggerType.WORKOUT_COMPLETED, dedupe="r-1")
    )
    recorder.run_all()
    assert len(transport.sent) == 1

    clock.advance(10)  # still inside the 30s cooldown window
    push_coach.handle_trigger(
        _trigger(TriggerType.WORKOUT_COMPLETED, dedupe="r-2")
    )
    assert recorder.jobs == []  # suppressed: nothing new scheduled
    assert len(llm.prompts) == 1
    assert len(transport.sent) == 1


def test_identical_context_and_reason_do_not_regenerate_after_cooldown(tables):
    _seed_user(steps=1000)
    clock = FakeClock()
    transport, recorder, llm = _config(push_coach, live=(USER_A,),
                                       llm=PromptRecordingLLM(),
                                       cooldown=30.0,
                                       clock=clock)
    push_coach.handle_trigger(
        _trigger(TriggerType.WORKOUT_COMPLETED, dedupe="r-1")
    )
    recorder.run_all()
    assert len(llm.prompts) == 1
    assert len(transport.sent) == 1

    clock.advance(31)  # cooldown over; same user + same context + same reason
    push_coach.handle_trigger(
        _trigger(TriggerType.WORKOUT_COMPLETED, dedupe="r-2")
    )
    recorder.run_all()
    # The reason-aware push key hit the existing CoachCache -> no second LLM call.
    assert len(llm.prompts) == 1
    assert len(transport.sent) == 1  # no duplicate coaching message


def test_changed_context_regenerates_fresh_coaching(tables):
    _seed_user(steps=1000)
    clock = FakeClock()
    transport, recorder, llm = _config(push_coach, live=(USER_A,),
                                       llm=PromptRecordingLLM(),
                                       cooldown=30.0,
                                       clock=clock)
    push_coach.handle_trigger(
        _trigger(TriggerType.WORKOUT_COMPLETED, dedupe="r-1")
    )
    recorder.run_all()
    assert len(llm.prompts) == 1

    clock.advance(31)
    _set_lifetime_steps(9000)  # the coach-relevant context really changed
    push_coach.handle_trigger(
        _trigger(TriggerType.WORKOUT_COMPLETED, dedupe="r-2")
    )
    recorder.run_all()

    assert len(llm.prompts) == 2  # fresh context -> fresh generation
    assert len(transport.sent) == 2
    assert "Total lifetime steps recorded: 9000" in llm.prompts[1]


def test_same_context_but_different_reason_regenerates(tables):
    """Push dedupe is reason-aware: a territory push minutes after a workout
    push on the SAME fitness context is still worth generating."""
    _seed_user(steps=1000)
    clock = FakeClock()
    transport, recorder, llm = _config(push_coach, live=(USER_A,),
                                       llm=PromptRecordingLLM(),
                                       cooldown=30.0,
                                       clock=clock)
    push_coach.handle_trigger(
        _trigger(TriggerType.WORKOUT_COMPLETED, dedupe="r-1")
    )
    recorder.run_all()
    assert len(llm.prompts) == 1

    clock.advance(31)  # context unchanged (still 1000 steps)
    push_coach.handle_trigger(
        _trigger(TriggerType.TERRITORY_CAPTURED, dedupe="h-1")
    )
    recorder.run_all()

    assert len(llm.prompts) == 2  # different reason -> new push
    assert len(transport.sent) == 2
    assert "captured new territory" in llm.prompts[1]


def test_users_are_isolated_in_coalescing_and_delivery(tables):
    transport, recorder, llm = _config(push_coach, live=(USER_A, USER_B),
                                       llm=PromptRecordingLLM(), cooldown=30.0)
    # A's burst: two triggers while armed fold into A's single generation.
    push_coach.handle_trigger(_trigger(TriggerType.WORKOUT_COMPLETED,
                                       uid=USER_A, dedupe="a-1"))
    push_coach.handle_trigger(_trigger(TriggerType.TERRITORY_CAPTURED,
                                       uid=USER_A, dedupe="a-2"))
    # B fires at the same instant: A being armed must NOT block B.
    push_coach.handle_trigger(_trigger(TriggerType.WORKOUT_COMPLETED,
                                       uid=USER_B, dedupe="b-1"))

    assert len(recorder.jobs) == 2  # one per user, not one global
    recorder.run_all()

    assert len(llm.prompts) == 2
    assert len(transport.sent) == 2
    assert {dest for dest, _ in transport.sent} == {USER_A, USER_B}


# ─────────────────────────────────────────────────────────────────────────────
# Failure containment
# ─────────────────────────────────────────────────────────────────────────────


def test_llm_failure_is_contained_no_fake_message_and_next_trigger_survives(tables):
    _seed_user(steps=1000)
    clock = FakeClock()
    llm = FlakyLLM()
    transport, recorder, _ = _config(push_coach, live=(USER_A,), llm=llm,
                                     cooldown=30.0, clock=clock)

    push_coach.handle_trigger(_trigger(TriggerType.WORKOUT_COMPLETED, dedupe="r-1"))
    recorder.run_all()  # must NOT raise into the test / producer

    assert len(llm.prompts) == 1
    assert transport.sent == []  # a failed generation delivers NO fake message

    clock.advance(31)  # the failure must not wedge the user's push state
    push_coach.handle_trigger(_trigger(TriggerType.WORKOUT_COMPLETED, dedupe="r-2"))
    recorder.run_all()

    assert llm.calls == 2  # recovered: the next real trigger generated
    assert len(transport.sent) == 1
    assert _delivered_message(transport)["coach"]["message"].startswith(
        "Recovered"
    )


def test_broken_ws_delivery_never_breaks_generation_or_future_pushes(tables):
    _seed_user(steps=1000)
    clock = FakeClock()
    llm = PromptRecordingLLM()
    transport = ExplodingTransport(USER_A)
    recorder = JobRecorder()
    push_coach.enabled = True
    push_coach.ws = transport
    push_coach.cache = CoachCache()
    push_coach.session_factory = lambda: Session(engine)
    push_coach.embedding_factory = lambda: FakeEmbeddingProvider()
    push_coach.llm_factory = lambda: llm
    push_coach.cooldown_seconds = 30.0
    push_coach.now = clock
    push_coach.schedule = recorder

    push_coach.handle_trigger(_trigger(TriggerType.WORKOUT_COMPLETED, dedupe="r-1"))
    recorder.run_all()  # send fails inside; must not propagate

    # Generation still happened; the broken client only lost the delivery.
    assert len(llm.prompts) == 1
    assert len(transport.sent) == 1  # the attempt was made

    clock.advance(31)  # the delivery failure must not wedge the user
    # A DIFFERENT reason (territory) is a fresh push, not a cache dedupe of the
    # already-generated workout message — proves the pipeline still works.
    push_coach.handle_trigger(_trigger(TriggerType.TERRITORY_CAPTURED, dedupe="r-2"))
    recorder.run_all()
    assert len(llm.prompts) == 2
    assert len(transport.sent) == 2


# ─────────────────────────────────────────────────────────────────────────────
# Pull path unchanged
# ─────────────────────────────────────────────────────────────────────────────


def test_pull_coach_path_unchanged_no_event_context(tables):
    """GET /api/v1/coach calls generate_coaching WITHOUT event_context; prove
    that path's prompt carries no push reason and still generates."""
    _seed_user(steps=5000)
    with Session(engine) as session:
        llm = PromptRecordingLLM()
        result = coach_service.generate_coaching(
            session, user_id=uuid.UUID(USER_A),
            embedding_provider=FakeEmbeddingProvider(), llm_provider=llm,
        )
        assert result.message == llm.message
        assert "Why this message is being generated" not in llm.prompts[0]


# ─────────────────────────────────────────────────────────────────────────────
# Integration: real engine -> real WS client -> real coaching_message
# ─────────────────────────────────────────────────────────────────────────────


def test_real_trigger_reaches_two_ws_clients_as_coaching_message(client):
    """End-to-end M8.3A, deterministic and API-key-free: process_run_sync emits
    a real trigger through the module trigger engine; PushCoach schedules one
    coalesced background generation (fake embedding + LLM); both of the user's
    live M8.2 WebSocket sessions receive the raw ``coaching_trigger`` followed
    by the AI ``coaching_message`` with real CoachResponse fields."""
    _seed_user(steps=0, user_id=USER_A)
    _ingest_knowledge()

    llm = PromptRecordingLLM()
    # Push must deliver over the REAL M8.2 manager (the transport the sockets
    # are registered on), not a FakeTransport.
    transport, recorder, _ = _config(
        push_coach, llm=llm, transport=ws_module.manager
    )

    with _Connect(client, USER_A) as ws_a:
        with _Connect(client, USER_A) as ws_b:
            # Both sessions must be registered before the run can emit.
            deadline = 3.0
            import time

            def _both_connected():
                return ws_module.manager.active_sessions(USER_A) == 2

            start = time.monotonic()
            while time.monotonic() - start < deadline:
                if _both_connected():
                    break
                time.sleep(0.01)
            assert _both_connected()

            run_id = f"push-integration-{uuid.uuid4().hex[:8]}"
            with Session(engine) as session:
                summary = process_run_sync(
                    session,
                    RunSyncPayload(
                        total_session_steps=1000,
                        hexes_to_steps={},
                        run_id=run_id,
                    ),
                    uuid.UUID(USER_A),
                )
            assert summary.already_processed is False

            # Producer was not blocked: exactly one background job was
            # scheduled and nothing was generated/delivered synchronously.
            assert len(recorder.jobs) == 1
            assert len(llm.prompts) == 0

            recorder.run_all()  # the AI push generation runs now

            # Each session gets the raw M8.2 trigger first, then the push.
            for ws in (ws_a, ws_b):
                raw = ws.receive_json()
                assert raw["type"] == "coaching_trigger"
                assert raw["trigger"]["user_id"] == USER_A

                push = ws.receive_json()
                assert set(push.keys()) == {"type", "trigger", "coach"}
                assert push["type"] == COACHING_MESSAGE_TYPE
                assert push["trigger"]["trigger_type"] == "workout_completed"
                assert push["trigger"]["event_id"] == run_id
                assert push["coach"]["message"] == llm.message
                assert push["coach"]["grounded"] is True  # fixture knowledge hit
                assert "context_fingerprint" in push["coach"]

            # One coalesced generation for the whole burst, delivered to both.
            assert len(llm.prompts) == 1
            assert "completed a run" in llm.prompts[0]
            # M8.1 engine recorded the moment normally (push is additive).
            accepted = trigger_engine.accepted(user_id=uuid.UUID(USER_A))
            assert any(t.event_id == run_id for t in accepted)
