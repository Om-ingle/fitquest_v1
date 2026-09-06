"""Recommendation engine: pure rule unit tests + endpoint tests."""
import uuid
from datetime import datetime, timedelta

import pytest

from app.api.dependencies import DEV_USER_ID
from app.modules.recommendations.schemas import FitnessContext
from app.modules.recommendations.service import recommend

# ─────────────────────────────────────────────────────────────────────────────
# Pure rules-engine unit tests (no DB, no HTTP)
# ─────────────────────────────────────────────────────────────────────────────

USER_ID = uuid.UUID(DEV_USER_ID)
NOW = datetime.utcnow()


def _context(**overrides) -> FitnessContext:
    defaults = dict(
        user_id=USER_ID,
        total_lifetime_steps=0,
        hexes_owned=0,
        recent_captures_7d=0,
        last_capture_at=None,
        total_defense_steps=0,
    )
    defaults.update(overrides)
    return FitnessContext(**defaults)


def test_r1_cold_start():
    result = recommend(_context())
    assert result.type == "STARTER"
    assert result.reason_code == "COLD_START"
    assert result.target_metric == "steps"
    assert result.target_value == 1000
    assert result.difficulty == "easy"
    assert "hexes_owned=0" in result.reason
    assert "total_lifetime_steps=0" in result.reason


def test_r2_lapsed_player_with_null_last_capture():
    # Has steps history but never captured a hex.
    result = recommend(_context(total_lifetime_steps=5000))
    assert result.type == "RECOVERY"
    assert result.reason_code == "LAPSED_PLAYER"
    assert result.target_value == 2000
    assert result.difficulty == "easy"
    assert "last_capture_at=None" in result.reason


def test_r2_lapsed_player_with_stale_capture():
    old = datetime.utcnow() - timedelta(days=3)
    result = recommend(_context(hexes_owned=2, last_capture_at=old, total_defense_steps=400))
    assert result.type == "RECOVERY"
    assert result.reason_code == "LAPSED_PLAYER"
    assert str(old.isoformat()) in result.reason
    assert "hexes_owned=2" in result.reason


def test_r2_not_triggered_when_capture_is_recent():
    recent = datetime.utcnow() - timedelta(days=1)
    result = recommend(_context(hexes_owned=2, last_capture_at=recent, recent_captures_7d=1))
    assert result.reason_code != "LAPSED_PLAYER"


def test_r3_territory_at_risk():
    # Captured 36h ago (not lapsed — under 2 days) but nothing new in the 7-day window.
    recent = datetime.utcnow() - timedelta(hours=36)
    result = recommend(
        _context(hexes_owned=3, recent_captures_7d=0, last_capture_at=recent, total_defense_steps=900)
    )
    assert result.type == "DEFENSE"
    assert result.reason_code == "TERRITORY_AT_RISK"
    assert result.target_metric == "hexes"
    assert result.target_value == 1
    assert result.difficulty == "medium"
    assert result.reason == "recent_captures_7d=0 while hexes_owned=3"


def test_r3_not_triggered_without_territory():
    result = recommend(_context(hexes_owned=0, recent_captures_7d=0, total_lifetime_steps=100))
    assert result.reason_code != "TERRITORY_AT_RISK"


def test_r4_consistent_performer():
    result = recommend(
        _context(
            hexes_owned=5,
            recent_captures_7d=3,
            last_capture_at=NOW,
            total_defense_steps=1500,
        )
    )
    assert result.type == "PROGRESS"
    assert result.reason_code == "CONSISTENT_PERFORMER"
    assert result.target_metric == "hexes"
    assert result.target_value == 3
    assert result.difficulty == "hard"
    assert result.reason == "recent_captures_7d=3"


def test_r5_default_maintain():
    # Recently active at moderate volume: not lapsed, not at-risk, not consistent.
    result = recommend(
        _context(
            hexes_owned=1,
            recent_captures_7d=1,
            last_capture_at=datetime.utcnow() - timedelta(days=1),
            total_defense_steps=200,
        )
    )
    assert result.type == "MAINTAIN"
    assert result.reason_code == "MAINTAIN"
    assert result.target_metric == "steps"
    assert result.target_value == 3000
    assert result.difficulty == "medium"
    assert "recent_captures_7d=1" in result.reason
    assert "hexes_owned=1" in result.reason


def test_priority_r2_beats_r3():
    # Matches BOTH R2 (stale capture) and R3 (hexes with 0 recent) → R2 wins.
    result = recommend(
        _context(
            hexes_owned=4,
            recent_captures_7d=0,
            last_capture_at=datetime.utcnow() - timedelta(days=10),
        )
    )
    assert result.reason_code == "LAPSED_PLAYER"


def test_priority_r1_beats_everything():
    # Zero footprint can only match R1 by definition; assert it wins over
    # the fallback and any other rule for the same context.
    result = recommend(_context(recent_captures_7d=0))
    assert result.reason_code == "COLD_START"


def test_deterministic_output():
    context = _context(
        hexes_owned=7,
        recent_captures_7d=4,
        last_capture_at=NOW,
        total_defense_steps=2100,
    )
    assert recommend(context) == recommend(context)


@pytest.mark.parametrize(
    "scenario",
    [
        _context(),
        _context(total_lifetime_steps=9000),
        _context(hexes_owned=2, last_capture_at=NOW),
        _context(hexes_owned=3, recent_captures_7d=0, last_capture_at=NOW),
        _context(hexes_owned=5, recent_captures_7d=6, last_capture_at=NOW),
        _context(hexes_owned=1, recent_captures_7d=2, last_capture_at=NOW),
    ],
)
def test_every_context_produces_a_valid_recommendation(scenario):
    result = recommend(scenario)
    assert result.type in {"STARTER", "RECOVERY", "DEFENSE", "PROGRESS", "MAINTAIN"}
    assert result.target_metric in {"steps", "hexes"}
    assert result.target_value > 0
    assert result.difficulty in {"easy", "medium", "hard"}
    assert result.title and result.description and result.reason


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint tests (real DB via the existing client fixture)
# ─────────────────────────────────────────────────────────────────────────────

def _create_dev_user(steps: int = 0):
    """Create the dev user directly (SQLite does not enforce the FK)."""
    from sqlmodel import Session

    from app.core.database import engine
    from app.modules.users.models import User

    with Session(engine) as db:
        user = User(id=uuid.UUID(DEV_USER_ID), username="devuser", total_lifetime_steps=steps)
        db.add(user)
        db.commit()


def _grant_hex(client, hex_id, defense=10):
    response = client.post(
        "/api/v1/map",
        json={"hex_id": hex_id, "king_id": DEV_USER_ID, "defense_score_steps": defense},
    )
    assert response.status_code == 201, response.text


def _age_last_capture(days: int):
    """Rewind the dev user's captured_at timestamps (SQLite, direct Session)."""
    from sqlmodel import Session, select

    from app.core.database import engine
    from app.modules.map.models import HexOwnership

    with Session(engine) as db:
        for hex_row in db.exec(
            select(HexOwnership).where(HexOwnership.king_id == uuid.UUID(DEV_USER_ID))
        ).all():
            hex_row.captured_at = datetime.utcnow() - timedelta(days=days)
            db.add(hex_row)
        db.commit()


def test_endpoint_empty_db_is_cold_start(client):
    response = client.get("/api/v1/recommendations")
    assert response.status_code == 200
    body = response.json()

    assert body["context"] == {
        "user_id": DEV_USER_ID,
        "total_lifetime_steps": 0,
        "hexes_owned": 0,
        "recent_captures_7d": 0,
        "last_capture_at": None,
        "total_defense_steps": 0,
        "activity_date": None,
        "steps_today": None,
        "active_minutes_today": None,
        "goal_steps": None,
        "goal_completed_today": None,
        "goal_progress_ratio": None,
    }
    assert body["recommendation"]["type"] == "STARTER"
    assert body["recommendation"]["reason_code"] == "COLD_START"
    assert body["generated_at"]


def test_endpoint_seeded_ownership_context_and_progress(client):
    _create_dev_user(steps=12450)
    for i in range(3):
        _grant_hex(client, f"8a2a1072b59ff{i:02x}", defense=100)

    body = client.get("/api/v1/recommendations").json()
    context = body["context"]
    assert context["total_lifetime_steps"] == 12450
    assert context["hexes_owned"] == 3
    assert context["recent_captures_7d"] == 3
    assert context["total_defense_steps"] == 300
    assert context["last_capture_at"] is not None

    recommendation = body["recommendation"]
    assert recommendation["type"] == "PROGRESS"
    assert recommendation["reason_code"] == "CONSISTENT_PERFORMER"
    assert recommendation["reason"] == "recent_captures_7d=3"


def test_endpoint_idle_territory_is_recovery_because_r2_outranks_r3(client):
    # DISCOVERED SPEC LIMITATION: R3 (TERRITORY_AT_RISK: recent_captures_7d==0
    # with hexes_owned>0) implies last_capture_at is older than 7 days, which
    # necessarily triggers R2 (LAPSED_PLAYER, >2 days) first. With real data
    # R3 is therefore shadowed by R2 — the R3 rule itself is covered by the
    # pure unit test above. This test pins the actual priority behavior.
    _create_dev_user(steps=5000)
    _grant_hex(client, "8a2a1072b59ffff", defense=250)
    _grant_hex(client, "8a2a1072b59fafff", defense=150)
    _age_last_capture(days=10)

    body = client.get("/api/v1/recommendations").json()
    context = body["context"]
    assert context["hexes_owned"] == 2
    assert context["recent_captures_7d"] == 0
    assert context["total_defense_steps"] == 400

    recommendation = body["recommendation"]
    assert recommendation["type"] == "RECOVERY"
    assert recommendation["reason_code"] == "LAPSED_PLAYER"
    assert "hexes_owned=2" in recommendation["reason"]


def test_endpoint_recovery_wins_over_defense(client):
    # Lapsed (no capture in >2 days) with territory → R2 beats R3.
    _create_dev_user(steps=8000)
    _grant_hex(client, "8a2a1072b59ffff")
    _age_last_capture(days=5)

    body = client.get("/api/v1/recommendations").json()
    assert body["recommendation"]["type"] == "RECOVERY"
    assert body["recommendation"]["reason_code"] == "LAPSED_PLAYER"


def test_endpoint_maintain_after_single_fresh_capture(client):
    _create_dev_user(steps=3000)
    _grant_hex(client, "8a2a1072b59ffff", defense=120)

    body = client.get("/api/v1/recommendations").json()
    assert body["recommendation"]["type"] == "MAINTAIN"
    assert body["recommendation"]["reason_code"] == "MAINTAIN"


def test_endpoint_is_deterministic(client):
    _create_dev_user(steps=2000)
    _grant_hex(client, "8a2a1072b59ffff")

    first = client.get("/api/v1/recommendations").json()
    second = client.get("/api/v1/recommendations").json()
    assert first["context"] == second["context"]
    assert first["recommendation"] == second["recommendation"]
