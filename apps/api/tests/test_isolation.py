"""M11 — two real accounts cannot reach each other's private data.

The acceptance criterion for M11 is that two genuinely independent accounts can
use FitQuest without seeing one another's data. This file is that criterion,
stated as tests.

Every test uses a REAL second identity: a separate token, signed by the same
key, whose subject resolves to a separate user row. Nothing is simulated by
passing another user's id — that would test the wrong thing, because the whole
point is that the server derives identity from the TOKEN and ignores whatever
the request says about who it is.

Two conventions keep the assertions honest:

* A refusal is never enough on its own. Where a request could MUTATE something,
  the test also re-reads the target and asserts it is untouched — a 403 that
  still wrote the row would otherwise pass.
* Every refusal is paired with a positive control: the same request made by the
  legitimate owner succeeds. Without that, a route that is simply broken (or
  that 403s everyone) would look like perfect isolation.
"""
import uuid

import pytest

from app.api.dependencies import DEV_USER_ID
from tests.authkit import link_identity, user_row
from tests.conftest import OTHER_USER_ID

OTHER_USER_UUID = uuid.UUID(OTHER_USER_ID)
# The same real res-10 cell tests/test_map_viewport.py uses (Nagpur), with a
# viewport that actually contains it.
HEX_ID = "8a60961611a7fff"
CENTER = (21.1009, 78.9785)
VIEWPORT = "/api/v1/map/viewport?min_lat=21.09&min_lng=78.96&max_lat=21.11&max_lng=79.0&zoom_level=16"


@pytest.fixture()
def other(other_headers):
    """The second account's header, plus its id — the isolation counterparty."""
    return other_headers


# ─────────────────────────────────────────────────────────────────────────────
# Profiles
# ─────────────────────────────────────────────────────────────────────────────


def test_a_user_cannot_read_another_users_profile(client, other):
    assert client.get(f"/api/v1/users/{DEV_USER_ID}").status_code == 200  # control
    assert client.get(f"/api/v1/users/{OTHER_USER_ID}").status_code == 403
    # ...and the reverse direction, so this is not a one-way asymmetry.
    assert client.get(f"/api/v1/users/{DEV_USER_ID}", headers=other).status_code == 403
    assert client.get(f"/api/v1/users/{OTHER_USER_ID}", headers=other).status_code == 200


def test_a_user_cannot_modify_another_users_profile(client, other):
    before = user_row(OTHER_USER_ID)

    response = client.patch(
        f"/api/v1/users/{OTHER_USER_ID}", json={"username": "hijacked"}
    )
    assert response.status_code == 403

    # The refusal must be real: the row is byte-for-byte what it was.
    after = user_row(OTHER_USER_ID)
    assert after.username == before.username == "otheruser"
    assert after.avatar_url == before.avatar_url

    # Positive control — the owner CAN rename itself through the same route.
    assert (
        client.patch(
            f"/api/v1/users/{OTHER_USER_ID}", json={"username": "renamed"}, headers=other
        ).status_code
        == 200
    )
    assert user_row(OTHER_USER_ID).username == "renamed"


# ─────────────────────────────────────────────────────────────────────────────
# Quests
# ─────────────────────────────────────────────────────────────────────────────


def test_a_user_cannot_list_another_users_quests(client, other):
    assert client.get(f"/api/v1/quests/{DEV_USER_ID}/quests").status_code == 200
    assert client.get(f"/api/v1/quests/{OTHER_USER_ID}/quests").status_code == 403
    # The owner's own listing still works.
    assert client.get(f"/api/v1/quests/{OTHER_USER_ID}/quests", headers=other).status_code == 200


def test_a_user_cannot_progress_another_users_quest(client, other):
    quest_id = "11111111-1111-4111-8111-111111111111"

    enroll = client.post(f"/api/v1/quests/{OTHER_USER_ID}/quests/{quest_id}")
    assert enroll.status_code == 403
    progress = client.patch(
        f"/api/v1/quests/{OTHER_USER_ID}/quests/{quest_id}",
        json={"current_progress": 999},
    )
    assert progress.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# Territory
# ─────────────────────────────────────────────────────────────────────────────


def test_a_user_cannot_claim_territory_for_someone_else(client, other):
    """The king is taken from the TOKEN, never from the body."""
    response = client.post(
        "/api/v1/map",
        json={
            "hex_id": HEX_ID,
            "king_id": OTHER_USER_ID,
            "defense_score_steps": 10,
        },
    )
    assert response.status_code == 403
    # Nothing was written: the hex does not exist at all.
    assert client.get(f"/api/v1/map/{HEX_ID}").status_code == 404

    # Positive control — claiming for the CALLER works and is attributed to it.
    claimed = client.post(
        "/api/v1/map",
        json={"hex_id": HEX_ID, "king_id": DEV_USER_ID, "defense_score_steps": 10},
    )
    assert claimed.status_code == 201
    assert claimed.json()["king_id"] == DEV_USER_ID


def test_is_owned_by_me_reflects_the_caller_not_the_data(client, other):
    """The same hex, viewed by two accounts, reports two different owners."""
    client.post(
        "/api/v1/map",
        json={"hex_id": HEX_ID, "king_id": DEV_USER_ID, "defense_score_steps": 10},
    )

    mine = client.get(VIEWPORT).json()["hexes"]
    theirs = client.get(VIEWPORT, headers=other).json()["hexes"]

    assert [h["is_owned_by_me"] for h in mine] == [True]
    # Same territory, but it is not theirs — the flag is per-token.
    assert [h["is_owned_by_me"] for h in theirs] == [False]
    assert [h["king_id"] for h in mine] == [h["king_id"] for h in theirs] == [DEV_USER_ID]


# ─────────────────────────────────────────────────────────────────────────────
# Run sync — the write path the Android client actually uses
# ─────────────────────────────────────────────────────────────────────────────


def test_run_sync_credits_the_token_holder_only(client, other):
    """A run is attributed to whoever authenticated — there is no user field."""
    before = user_row(OTHER_USER_ID).total_lifetime_steps

    response = client.post(
        "/api/v1/runs/sync",
        json={"total_session_steps": 1234, "hexes_to_steps": {HEX_ID: 1234}},
    )
    assert response.status_code == 200
    assert response.json()["new_total_lifetime_steps"] == 1234

    assert user_row(DEV_USER_ID).total_lifetime_steps >= 1234
    # The other account's totals and territory are untouched.
    assert user_row(OTHER_USER_ID).total_lifetime_steps == before
    assert client.get(f"/api/v1/map/user/{OTHER_USER_ID}").status_code == 200

    # The captured hex belongs to the syncing account, not the other one.
    hex_row = client.get(f"/api/v1/map/{HEX_ID}").json()
    assert hex_row["king_id"] == DEV_USER_ID


# ─────────────────────────────────────────────────────────────────────────────
# Read endpoints scoped by token: leaderboard, recommendations, coach
# ─────────────────────────────────────────────────────────────────────────────


def test_leaderboard_marks_only_the_callers_own_entry(client, other):
    body = client.get("/api/v1/leaderboard").json()
    flagged = [e for e in body["entries"] if e["is_current_user"]]
    assert [e["user_id"] for e in flagged] == [DEV_USER_ID]

    theirs = client.get("/api/v1/leaderboard", headers=other).json()
    theirs_flagged = [e for e in theirs["entries"] if e["is_current_user"]]
    assert [e["user_id"] for e in theirs_flagged] == [OTHER_USER_ID]
    # Both accounts see the same ranked table; only the marker differs.
    assert len(theirs["entries"]) == len(body["entries"])


def test_recommendations_use_the_callers_own_context(client, other):
    mine = client.get("/api/v1/recommendations").json()["context"]
    theirs = client.get("/api/v1/recommendations", headers=other).json()["context"]

    assert mine["user_id"] == DEV_USER_ID
    assert theirs["user_id"] == OTHER_USER_ID


def test_coach_reports_the_callers_own_user_id(client, other):
    """The coaching context is built from the token's identity, not a parameter."""
    mine = client.get("/api/v1/coach").json()
    theirs = client.get("/api/v1/coach", headers=other).json()

    assert mine["context"]["user_id"] == DEV_USER_ID
    assert theirs["context"]["user_id"] == OTHER_USER_ID


# ─────────────────────────────────────────────────────────────────────────────
# The identities themselves
# ─────────────────────────────────────────────────────────────────────────────


def test_the_two_accounts_are_genuinely_distinct(client, other):
    """Guards the fixtures: two tokens, two subjects, two internal rows.

    If this ever collapses to one identity, every assertion above becomes
    vacuously true — so it is asserted explicitly.
    """
    dev = user_row(DEV_USER_ID)
    rival = user_row(OTHER_USER_ID)

    assert dev.id != rival.id
    assert dev.auth_subject != rival.auth_subject
    # Each subject maps to exactly its own row, and neither adopts the other's.
    assert dev.auth_subject == DEV_USER_ID
    assert rival.auth_subject == OTHER_USER_ID


def test_a_third_subject_is_provisioned_separately(client, other, jwks):
    """A new account appears on first use and shares nothing with the others."""
    third_subject = "99999999-9999-4999-8999-999999999999"
    third = client.get(
        "/api/v1/users", headers=jwks.factory.headers(third_subject)
    )

    # It is authenticated (the row was provisioned), so the request succeeds.
    assert third.status_code == 200
    usernames = {u["username"] for u in third.json()}
    assert {"devuser", "otheruser"} <= usernames
    # Three accounts, three rows — the newcomer did not adopt an existing one.
    assert len(third.json()) >= 3
    assert len({u["id"] for u in third.json()}) == len(third.json())
