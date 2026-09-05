"""Territory leaderboard: ordering, ties, zero counts, top-N, current user."""
from app.api.dependencies import DEV_USER_ID


def _create_user(client, username):
    response = client.post("/api/v1/users", json={"username": username})
    assert response.status_code == 201
    return response.json()


def _grant_hexes(client, user_id, hex_ids):
    """Give a user ownership of fresh hexes via the existing map endpoint."""
    for hex_id in hex_ids:
        response = client.post(
            "/api/v1/map",
            json={"hex_id": hex_id, "king_id": user_id, "defense_score_steps": 10},
        )
        assert response.status_code == 201, response.text


def _dev_user_id():
    return DEV_USER_ID


def test_empty_leaderboard(client):
    response = client.get("/api/v1/leaderboard")
    assert response.status_code == 200
    body = response.json()
    assert body["metric"] == "hexes"
    assert body["total_players"] == 0
    assert body["entries"] == []
    assert body["current_user_entry"] is None


def test_leaderboard_orders_by_territory_count(client):
    low = _create_user(client, "low")
    high = _create_user(client, "high")
    _grant_hexes(client, low["id"], ["8a2a1072b59ffff"])
    _grant_hexes(client, high["id"], ["8a2a1072b4bffff", "8a2a1072b4dffff"])

    body = client.get("/api/v1/leaderboard").json()
    assert [e["username"] for e in body["entries"]] == ["high", "low"]
    assert body["entries"][0]["hexes_owned"] == 2
    assert body["entries"][1]["hexes_owned"] == 1
    assert body["entries"][0]["rank"] == 1
    assert body["entries"][1]["rank"] == 2


def test_zero_territory_users_are_included(client):
    _create_user(client, "hexless")
    hexer = _create_user(client, "hexer")
    _grant_hexes(client, hexer["id"], ["8a2a1072b59ffff"])

    body = client.get("/api/v1/leaderboard").json()
    zero = [e for e in body["entries"] if e["username"] == "hexless"]
    assert len(zero) == 1
    assert zero[0]["hexes_owned"] == 0


def test_equal_territory_counts_share_rank(client):
    first = _create_user(client, "aaa")
    second = _create_user(client, "bbb")
    _grant_hexes(client, first["id"], ["8a2a1072b59ffff"])
    _grant_hexes(client, second["id"], ["8a2a1072b4bffff"])

    body = client.get("/api/v1/leaderboard").json()
    assert body["entries"][0]["rank"] == body["entries"][1]["rank"] == 1


def test_top_n_limit(client):
    for i in range(4):
        _grant_hexes(client, _create_user(client, f"player{i}")["id"], [f"8a2a1072b59ff{i:02x}"])

    body = client.get("/api/v1/leaderboard?limit=2").json()
    assert len(body["entries"]) == 2
    assert body["total_players"] == 4


def test_current_user_rank_outside_top_n(client):
    # Dev user exists with 0 hexes; three rivals own territory.
    import uuid as uuid_mod

    from sqlmodel import Session

    from app.core.database import engine
    from app.modules.users.models import User

    with Session(engine) as db:
        db.add(User(id=uuid_mod.UUID(DEV_USER_ID), username="devuser"))
        db.commit()

    for i in range(3):
        _grant_hexes(client, _create_user(client, f"rival{i}")["id"], [f"8a2a1072b4bf{i:02x}"])

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
