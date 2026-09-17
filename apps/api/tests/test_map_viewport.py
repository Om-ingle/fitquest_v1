"""Shared-map viewport: bbox filtering, zoom behavior, edge cases."""
import uuid as uuid_mod

import h3
from sqlmodel import Session

from app.api.dependencies import DEV_USER_ID
from app.core.database import engine
from app.modules.map.service import create_hex

# Real res-10 H3 cells around a fixed location (Nagpur test area).
CENTER = (21.1009, 78.9785)
CELL_CENTER = h3.latlng_to_cell(CENTER[0], CENTER[1], 10)
# ~1 km north — several hex edges away, clearly outside a tight bbox.
CELL_NORTH = h3.latlng_to_cell(CENTER[0] + 0.01, CENTER[1], 10)
# ~1 km east.
CELL_EAST = h3.latlng_to_cell(CENTER[0], CENTER[1] + 0.01, 10)


def _create_user(client, username):
    response = client.post("/api/v1/users", json={"username": username})
    assert response.status_code == 201
    return response.json()


def _seed_hex(king_id, hex_id, defense=10):
    """Give another player territory via the service layer, not the API.

    M11: `POST /api/v1/map` refuses to claim territory for anyone but the
    authenticated caller, so it can no longer be used to fabricate a hex owned
    by someone else. That is the correct behaviour — in the real system another
    player's territory arrives through run sync — so these fixtures seed the
    row directly rather than asking the API to do something it now forbids.
    """
    with Session(engine) as db:
        create_hex(db, hex_id, uuid_mod.UUID(str(king_id)), defense)


def _claim_own_hex(client, hex_id, defense=10):
    """The API path a real client uses: claim a hex for the caller's account."""
    response = client.post(
        "/api/v1/map",
        json={
            "hex_id": hex_id,
            "king_id": DEV_USER_ID,
            "defense_score_steps": defense,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _viewport(client, min_lat, min_lng, max_lat, max_lng, zoom=16.0):
    response = client.get(
        "/api/v1/map/viewport",
        params={
            "min_lat": min_lat,
            "min_lng": min_lng,
            "max_lat": max_lat,
            "max_lng": max_lng,
            "zoom_level": zoom,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_hex_inside_bbox_is_returned(client):
    owner = _create_user(client, "owner")
    _seed_hex(owner["id"], CELL_CENTER)

    body = _viewport(
        client,
        min_lat=CENTER[0] - 0.01,
        min_lng=CENTER[1] - 0.01,
        max_lat=CENTER[0] + 0.01,
        max_lng=CENTER[1] + 0.01,
    )
    assert body["is_aggregated"] is False
    assert [h["hex_id"] for h in body["hexes"]] == [CELL_CENTER]
    entry = body["hexes"][0]
    assert entry["king_username"] == "owner"
    assert entry["king_id"] == owner["id"]
    assert entry["is_owned_by_me"] is False


def test_hex_outside_bbox_is_excluded(client):
    owner = _create_user(client, "owner")
    _seed_hex(owner["id"], CELL_NORTH)

    # Tight bbox around CENTER, far from the ~1km-away northern hex.
    body = _viewport(
        client,
        min_lat=CENTER[0] - 0.001,
        min_lng=CENTER[1] - 0.001,
        max_lat=CENTER[0] + 0.001,
        max_lng=CENTER[1] + 0.001,
    )
    assert body["hexes"] == []


def test_multiple_owned_hexes_filtered_by_bbox(client):
    owner = _create_user(client, "owner")
    _seed_hex(owner["id"], CELL_CENTER)
    _seed_hex(owner["id"], CELL_NORTH)
    _seed_hex(owner["id"], CELL_EAST)

    # Wide bbox (~2km) contains everything.
    body = _viewport(
        client,
        min_lat=CENTER[0] - 0.02,
        min_lng=CENTER[1] - 0.02,
        max_lat=CENTER[0] + 0.02,
        max_lng=CENTER[1] + 0.02,
    )
    assert set(h["hex_id"] for h in body["hexes"]) == {
        CELL_CENTER,
        CELL_NORTH,
        CELL_EAST,
    }

    # Narrow bbox around the center only excludes the northern/eastern hexes.
    narrow = _viewport(
        client,
        min_lat=CENTER[0] - 0.002,
        min_lng=CENTER[1] - 0.002,
        max_lat=CENTER[0] + 0.002,
        max_lng=CENTER[1] + 0.002,
    )
    assert [h["hex_id"] for h in narrow["hexes"]] == [CELL_CENTER]


def test_hex_center_just_outside_bbox_is_included_via_padding(client):
    """A hex whose boundary clips the viewport must still be returned."""
    _claim_own_hex(client, CELL_CENTER)
    center_lat, center_lng = h3.cell_to_latlng(CELL_CENTER)

    # Bbox northern edge sits just south of the hex center — the cell
    # boundary still overlaps the viewport, so it must be included.
    body = _viewport(
        client,
        min_lat=center_lat - 0.002,
        min_lng=center_lng - 0.002,
        max_lat=center_lat - 0.0002,
        max_lng=center_lng + 0.002,
    )
    assert CELL_CENTER in [h["hex_id"] for h in body["hexes"]]


def test_is_owned_by_me_for_current_user(client):
    """`is_owned_by_me` is decided by the TOKEN, not by anything the client sent.

    The dev user row is created by the auth fixtures (linked to its subject, as
    seed.py leaves it), so this test no longer inserts one itself — a second
    insert would collide with the primary key.
    """
    _claim_own_hex(client, CELL_CENTER)

    body = _viewport(
        client,
        min_lat=CENTER[0] - 0.01,
        min_lng=CENTER[1] - 0.01,
        max_lat=CENTER[0] + 0.01,
        max_lng=CENTER[1] + 0.01,
    )
    assert body["hexes"][0]["is_owned_by_me"] is True


def test_zoom_below_14_returns_aggregated_placeholder(client):
    _claim_own_hex(client, CELL_CENTER)

    body = _viewport(
        client,
        min_lat=CENTER[0] - 0.01,
        min_lng=CENTER[1] - 0.01,
        max_lat=CENTER[0] + 0.01,
        max_lng=CENTER[1] + 0.01,
        zoom=12.0,
    )
    assert body["is_aggregated"] is True
    assert body["hexes"] == []
    assert body["heatmaps"] == []


def test_zoom_boundary_at_14_returns_detail(client):
    _claim_own_hex(client, CELL_CENTER)

    body = _viewport(
        client,
        min_lat=CENTER[0] - 0.01,
        min_lng=CENTER[1] - 0.01,
        max_lat=CENTER[0] + 0.01,
        max_lng=CENTER[1] + 0.01,
        zoom=14.0,
    )
    assert body["is_aggregated"] is False
    assert len(body["hexes"]) == 1


def test_empty_viewport_returns_no_hexes(client):
    # No hexes exist at all.
    body = _viewport(
        client,
        min_lat=CENTER[0] - 0.01,
        min_lng=CENTER[1] - 0.01,
        max_lat=CENTER[0] + 0.01,
        max_lng=CENTER[1] + 0.01,
    )
    assert body["is_aggregated"] is False
    assert body["hexes"] == []


def test_invalid_bbox_rejected(client):
    response = client.get(
        "/api/v1/map/viewport",
        params={
            "min_lat": 22.0,
            "min_lng": 78.0,
            "max_lat": 21.0,  # min_lat > max_lat — invalid
            "max_lng": 79.0,
            "zoom_level": 16.0,
        },
    )
    assert response.status_code == 400


def test_get_hex_by_id_still_works(client):
    """Regression: the single-hex lookup endpoint is unchanged."""
    owner = _create_user(client, "owner")
    _seed_hex(owner["id"], CELL_CENTER, defense=42)

    response = client.get(f"/api/v1/map/{CELL_CENTER}")
    assert response.status_code == 200
    body = response.json()
    assert body["king_id"] == owner["id"]
    assert body["defense_score_steps"] == 42

