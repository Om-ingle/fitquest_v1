"""Territory leaderboard: ordering, ties, zero counts, top-N, current user."""
import uuid as uuid_mod

from sqlmodel import Session

from app.api.dependencies import DEV_USER_ID
from app.core.database import engine
from app.modules.map.service import create_hex


def _create_user(client, username):
    response = client.post("/api/v1/users", json={"username": username})
    assert response.status_code == 201
    return response.json()


def _grant_hexes(user_id, hex_ids):
    """Give a user ownership of hexes — seeded at the service layer.

    M11 — deliberately NOT through ``POST /api/v1/map``: that endpoint now
    refuses to claim territory for anyone but the authenticated caller, because
    a real client only ever syncs its OWN hexes. Another player's territory
    arrives through their own run sync, so writing the row directly is both
    permitted and more faithful to how it appears in production.
    """
    with Session(engine) as db:
        for hex_id in hex_ids:
            create_hex(db, hex_id, uuid_mod.UUID(str(user_id)), 10)


def test_empty_leaderboard(client):
    """A fresh schema holds exactly one player: the authenticated account.

    M11 — the caller's own row exists before any test data (conftest links it
    so requests can authenticate at all), so "empty" now means nobody has
    captured anything, not that the table has no rows.
    """
    response = client.get("/api/v1/leaderboard")
    assert response.status_code == 200
    body = response.json()
    assert body["metric"] == "hexes"
    assert body["total_players"] == 1
    assert [e["username"] for e in body["entries"]] == ["devuser"]
    assert body["entries"][0]["hexes_owned"] == 0
    # The caller is already in the list, so no separate entry accompanies it.
    assert body["current_user_entry"] is None


def test_leaderboard_orders_by_territory_count(client):
    low = _create_user(client, "low")
    high = _create_user(client, "high")
    _grant_hexes(low["id"], ["8a2a1072b59ffff"])
    _grant_hexes(high["id"], ["8a2a1072b4bffff", "8a2a1072b4dffff"])

    body = client.get("/api/v1/leaderboard").json()
    assert [e["username"] for e in body["entries"][:2]] == ["high", "low"]
    assert body["entries"][0]["hexes_owned"] == 2
    assert body["entries"][1]["hexes_owned"] == 1
    assert body["entries"][0]["rank"] == 1
    assert body["entries"][1]["rank"] == 2


def test_zero_territory_users_are_included(client):
    _create_user(client, "hexless")
    hexer = _create_user(client, "hexer")
    _grant_hexes(hexer["id"], ["8a2a1072b59ffff"])

    body = client.get("/api/v1/leaderboard").json()
    zero = [e for e in body["entries"] if e["username"] == "hexless"]
    assert len(zero) == 1
    assert zero[0]["hexes_owned"] == 0


def test_equal_territory_counts_share_rank(client):
    first = _create_user(client, "aaa")
    second = _create_user(client, "bbb")
    _grant_hexes(first["id"], ["8a2a1072b59ffff"])
    _grant_hexes(second["id"], ["8a2a1072b4bffff"])

    body = client.get("/api/v1/leaderboard").json()
    # The authenticated dev account also has 0 hexes, so the tie group at rank
    # 1 is the two rivals; dev follows on its own rank.
    assert body["entries"][0]["rank"] == body["entries"][1]["rank"] == 1


def test_top_n_limit(client):
    for i in range(4):
        _grant_hexes(_create_user(client, f"player{i}")["id"], [f"8a2a1072b59ff{i:02x}"])

    body = client.get("/api/v1/leaderboard?limit=2").json()
    assert len(body["entries"]) == 2
    # The 4 players plus the authenticated account already in the schema.
    assert body["total_players"] == 5


def test_current_user_rank_outside_top_n(client):
    """The caller is outside the displayed cut, so it gets its own entry.

    M11 — no dev row is inserted here: the authenticated client already has
    one (conftest links it), and a second insert would collide on the primary
    key.
    """
    for i in range(3):
        _grant_hexes(_create_user(client, f"rival{i}")["id"], [f"8a2a1072b4bf{i:02x}"])

    body = client.get("/api/v1/leaderboard?limit=2").json()
    # Dev user is outside the top-2 cut.
    assert body["current_user_entry"] is not None
    assert body["current_user_entry"]["is_current_user"] is True
    assert body["current_user_entry"]["hexes_owned"] == 0
    assert body["current_user_entry"]["rank"] == 4
    # Inside the top-N cut the separate entry is omitted...
    full = client.get("/api/v1/leaderboard?limit=10").json()
    assert full["current_user_entry"] is None
    # ...but the dev user still appears in the full list.
    assert any(e["is_current_user"] for e in full["entries"])
