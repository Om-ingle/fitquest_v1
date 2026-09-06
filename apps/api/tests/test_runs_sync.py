"""API-level tests for user creation and the run-sync turf-war logic."""
import uuid

from sqlmodel import Session

from app.api.dependencies import DEV_USER_ID
from app.core.database import engine
from app.modules.users.models import User


def _create_user(client, username):
    response = client.post("/api/v1/users", json={"username": username})
    assert response.status_code == 201
    return response.json()


def _seed_dev_user():
    """The dev user must exist for lifetime-step tracking (seed.py creates it
    in real environments; SQLite does not enforce the FK, so tests must)."""
    with Session(engine) as db:
        if db.get(User, uuid.UUID(DEV_USER_ID)) is None:
            db.add(User(id=uuid.UUID(DEV_USER_ID), username="devuser"))
            db.commit()


def test_create_and_get_user(client):
    created = _create_user(client, "runner1")
    response = client.get(f"/api/v1/users/{created['id']}")
    assert response.status_code == 200
    assert response.json()["username"] == "runner1"


def test_duplicate_username_rejected(client):
    _create_user(client, "runner1")
    response = client.post("/api/v1/users", json={"username": "runner1"})
    assert response.status_code == 409


def test_run_sync_captures_new_hexes(client):
    payload = {
        "total_session_steps": 500,
        "hexes_to_steps": {"8a2a1072b59ffff": 300, "8a2a1072b4bffff": 200},
    }
    response = client.post("/api/v1/runs/sync", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["hexes_newly_captured"] == 2
    assert body["hexes_stolen"] == 0
    assert body["hexes_defended"] == 0
    assert body["xp_earned"] == 100  # 50 XP per new hex

    # Ownership rows were created for the dev user.
    hex_response = client.get(f"/api/v1/map/8a2a1072b59ffff")
    assert hex_response.status_code == 200
    assert hex_response.json()["king_id"] == DEV_USER_ID
    assert hex_response.json()["defense_score_steps"] == 300


def test_run_sync_defends_owned_hex(client):
    client.post(
        "/api/v1/runs/sync",
        json={"total_session_steps": 300, "hexes_to_steps": {"8a2a1072b59ffff": 300}},
    )
    response = client.post(
        "/api/v1/runs/sync",
        json={"total_session_steps": 200, "hexes_to_steps": {"8a2a1072b59ffff": 200}},
    )
    body = response.json()
    assert body["hexes_defended"] == 1
    assert body["xp_earned"] == 10
    # Defense score accumulates across sessions.
    hex_response = client.get("/api/v1/map/8a2a1072b59ffff")
    assert hex_response.json()["defense_score_steps"] == 500


def test_run_sync_steals_rival_hex(client):
    rival = _create_user(client, "rival")
    client.post(
        "/api/v1/map",
        json={"hex_id": "8a2a1072b59ffff", "king_id": rival["id"], "defense_score_steps": 100},
    )

    response = client.post(
        "/api/v1/runs/sync",
        json={"total_session_steps": 150, "hexes_to_steps": {"8a2a1072b59ffff": 150}},
    )
    body = response.json()
    assert body["hexes_stolen"] == 1
    assert body["xp_earned"] == 100

    hex_response = client.get("/api/v1/map/8a2a1072b59ffff")
    stolen = hex_response.json()
    assert stolen["king_id"] == DEV_USER_ID
    assert stolen["times_stolen"] == 1


def test_run_sync_does_not_steal_when_defense_holds(client):
    rival = _create_user(client, "rival")
    client.post(
        "/api/v1/map",
        json={"hex_id": "8a2a1072b59ffff", "king_id": rival["id"], "defense_score_steps": 500},
    )

    response = client.post(
        "/api/v1/runs/sync",
        json={"total_session_steps": 100, "hexes_to_steps": {"8a2a1072b59ffff": 100}},
    )
    body = response.json()
    assert body["hexes_stolen"] == 0
    assert body["hexes_defended"] == 0
    assert body["hexes_newly_captured"] == 0

    hex_response = client.get("/api/v1/map/8a2a1072b59ffff")
    assert hex_response.json()["king_id"] == rival["id"]


def test_run_sync_with_no_hexes_updates_steps_only(client):
    """Android sends this shape when a run ends outside any captured hex."""
    _seed_dev_user()

    response = client.post(
        "/api/v1/runs/sync",
        json={"total_session_steps": 250, "hexes_to_steps": {}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["xp_earned"] == 0
    assert body["hexes_newly_captured"] == 0
    assert body["hexes_defended"] == 0
    assert body["hexes_stolen"] == 0
    assert body["new_total_lifetime_steps"] == 250


def test_run_sync_replay_same_run_id_is_idempotent(client):
    """A retried sync carrying a run_id already applied must not re-credit."""
    _seed_dev_user()
    run_id = "b7853a0d-1234-4a6e-9c00-000000000001"
    payload = {
        "run_id": run_id,
        "total_session_steps": 631,
        "hexes_to_steps": {"8a2a1072b59ffff": 300, "8a2a1072b4bffff": 200},
    }

    first = client.post("/api/v1/runs/sync", json=payload)
    assert first.status_code == 200
    assert first.json()["already_processed"] is False
    assert first.json()["xp_earned"] == 100
    assert first.json()["new_total_lifetime_steps"] == 631

    replay = client.post("/api/v1/runs/sync", json=payload)
    assert replay.status_code == 200
    body = replay.json()
    assert body["already_processed"] is True
    assert body["xp_earned"] == 0
    assert body["hexes_newly_captured"] == 0
    assert body["hexes_defended"] == 0
    assert body["new_total_lifetime_steps"] == 631  # not 631 + 631

    # The hex was only minted once.
    hex_response = client.get("/api/v1/map/8a2a1072b59ffff")
    assert hex_response.status_code == 200
    assert hex_response.json()["defense_score_steps"] == 300

    # The replay ledger recorded the run exactly once.
    from sqlmodel import select
    from app.modules.runs.models import RunSession
    with Session(engine) as db:
        assert db.exec(select(RunSession).where(RunSession.id == run_id)).all().__len__() == 1


def test_run_sync_legacy_payload_without_run_id_still_applies_on_replay(client):
    """Old clients send no run_id; a duplicate POST must keep old behaviour
    (i.e. accumulate) so the dedupe guard never silently drops them."""
    _seed_dev_user()
    payload = {"total_session_steps": 250, "hexes_to_steps": {}}

    first = client.post("/api/v1/runs/sync", json=payload)
    second = client.post("/api/v1/runs/sync", json=payload)
    assert first.json()["already_processed"] is False
    assert second.json()["already_processed"] is False
    assert first.json()["new_total_lifetime_steps"] == 250
    assert second.json()["new_total_lifetime_steps"] == 500
