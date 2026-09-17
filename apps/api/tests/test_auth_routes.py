"""M11 — every /api/v1 route requires a verified token; /health stays public.

The enforcement is attached to the API router rather than to each route
(app/api/router.py), so a new endpoint is authenticated by construction rather
than by remembering. This file is the proof of that property, and it is written
to fail if the property is lost:

* ``test_route_table_is_fully_covered`` compares the app's REAL route table
  against the table below. Adding a route without adding it here fails the
  guard, so no endpoint can be left unexamined.
* every route in the table is then actually CALLED with no token, with a
  malformed token, and with a token signed by an unpublished key — and must
  answer 401 each time.

Calling the routes (rather than introspecting their dependency lists) is
deliberate: it asserts the status a client sees, and it cannot be fooled by a
dependency that is present but ineffective.
"""
import pytest

from app.api.dependencies import DEV_USER_ID
from app.main import app
from app.modules.rag.constants import EMBEDDING_DIMENSION

# A second, valid-looking account id — never the caller's.
OTHER_USER_ID = "00000000-0000-4000-8000-00000000c0de"
HEX_ID = "8a2a1072b59ffff"
QUEST_ID = "11111111-1111-4111-8111-111111111111"

_VIEWPORT_QUERY = "min_lat=21.0&min_lng=78.0&max_lat=22.0&max_lng=79.0&zoom_level=16"


class _Route:
    """One HTTP route, with everything needed to actually call it."""

    def __init__(self, method, template, url, json_body=None):
        self.method = method
        self.template = template
        self.url = url
        self.json_body = json_body

    @property
    def id(self) -> str:
        return f"{self.method} {self.template}"


# Every /api/v1 route the app serves, with a REQUEST THAT WOULD OTHERWISE BE
# VALID. The bodies and path values are deliberately well-formed so a 401 can
# only come from the auth dependency — a 422 would prove nothing.
PROTECTED_ROUTES = [
    _Route("GET", "/api/v1/coach", "/api/v1/coach"),
    _Route("GET", "/api/v1/leaderboard", "/api/v1/leaderboard"),
    _Route(
        "POST",
        "/api/v1/map",
        "/api/v1/map",
        {"hex_id": HEX_ID, "king_id": DEV_USER_ID, "defense_score_steps": 1},
    ),
    _Route("GET", "/api/v1/map/viewport", f"/api/v1/map/viewport?{_VIEWPORT_QUERY}"),
    _Route("GET", "/api/v1/map/{hex_id}", f"/api/v1/map/{HEX_ID}"),
    _Route(
        "PATCH",
        "/api/v1/map/{hex_id}",
        f"/api/v1/map/{HEX_ID}",
        {"defense_score_steps": 5},
    ),
    _Route("GET", "/api/v1/map/user/{user_id}", f"/api/v1/map/user/{DEV_USER_ID}"),
    _Route("GET", "/api/v1/quests", "/api/v1/quests"),
    _Route(
        "POST",
        "/api/v1/quests",
        "/api/v1/quests",
        {
            "title": "Daily steps",
            "description": "Walk every day",
            "target_metric": "steps",
            "target_value": 5000,
        },
    ),
    _Route("GET", "/api/v1/quests/{quest_id}", f"/api/v1/quests/{QUEST_ID}"),
    _Route(
        "GET", "/api/v1/quests/{user_id}/quests", f"/api/v1/quests/{DEV_USER_ID}/quests"
    ),
    _Route(
        "POST",
        "/api/v1/quests/{user_id}/quests/{quest_id}",
        f"/api/v1/quests/{DEV_USER_ID}/quests/{QUEST_ID}",
    ),
    _Route(
        "PATCH",
        "/api/v1/quests/{user_id}/quests/{quest_id}",
        f"/api/v1/quests/{DEV_USER_ID}/quests/{QUEST_ID}",
        {"current_progress": 1},
    ),
    _Route("GET", "/api/v1/rag/documents", "/api/v1/rag/documents"),
    _Route(
        "POST",
        "/api/v1/rag/documents",
        "/api/v1/rag/documents",
        {"title": "t", "source": "s", "content": "c"},
    ),
    _Route(
        "POST",
        "/api/v1/rag/retrieve",
        "/api/v1/rag/retrieve",
        {"query_embedding": [0.0] * EMBEDDING_DIMENSION},
    ),
    _Route("GET", "/api/v1/recommendations", "/api/v1/recommendations"),
    _Route(
        "POST",
        "/api/v1/runs/sync",
        "/api/v1/runs/sync",
        {"total_session_steps": 0, "hexes_to_steps": {}},
    ),
    _Route("GET", "/api/v1/users", "/api/v1/users"),
    _Route("POST", "/api/v1/users", "/api/v1/users", {"username": "someone"}),
    _Route("GET", "/api/v1/users/{user_id}", f"/api/v1/users/{DEV_USER_ID}"),
    _Route(
        "PATCH",
        "/api/v1/users/{user_id}",
        f"/api/v1/users/{DEV_USER_ID}",
        {"avatar_url": "https://example.com/a.png"},
    ),
]


def _openapi_http_routes() -> set[tuple[str, str]]:
    """(method, path) for every HTTP route the app publishes, including /health."""
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }


def test_route_table_is_fully_covered():
    """The guard: this table must match the app's real route table exactly.

    A new endpoint fails here until it is listed above and therefore called by
    the assertions below. A REMOVED endpoint fails too, so the table cannot rot
    into describing routes that no longer exist.
    """
    declared = {(route.method, route.template) for route in PROTECTED_ROUTES}
    actual = _openapi_http_routes() - {("GET", "/health")}

    assert actual - declared == set(), (
        "reached the API without an unauthenticated-access assertion: "
        f"{sorted(actual - declared)}"
    )
    assert declared - actual == set(), (
        f"listed here but no longer served: {sorted(declared - actual)}"
    )


def test_health_stays_public(anon_client):
    """The one deliberate exception: a liveness probe must not need credentials."""
    response = anon_client.get("/health")

    assert response.status_code == 200


@pytest.mark.parametrize("route", PROTECTED_ROUTES, ids=[r.id for r in PROTECTED_ROUTES])
def test_route_rejects_a_request_with_no_token(anon_client, route):
    response = anon_client.request(route.method, route.url, json=route.json_body)

    assert response.status_code == 401, (
        f"{route.id} answered {response.status_code} without credentials"
    )
    # A 401 must tell the client HOW to authenticate.
    assert response.headers.get("WWW-Authenticate") == "Bearer"


@pytest.mark.parametrize("route", PROTECTED_ROUTES, ids=[r.id for r in PROTECTED_ROUTES])
def test_route_rejects_a_malformed_token(anon_client, route):
    response = anon_client.request(
        route.method,
        route.url,
        json=route.json_body,
        headers={"Authorization": "Bearer not.a.jwt"},
    )

    assert response.status_code == 401, (
        f"{route.id} answered {response.status_code} for a malformed token"
    )


@pytest.mark.parametrize("route", PROTECTED_ROUTES, ids=[r.id for r in PROTECTED_ROUTES])
def test_route_rejects_a_token_signed_by_an_unpublished_key(anon_client, jwks, route):
    """Signature verification is not optional on any route.

    This is the case that separates "checks for a token" from "verifies a
    token": the header is well-formed and the claims are valid, so only the
    signature stands in the way.
    """
    forged = jwks.factory.foreign_token(jwks.foreign, DEV_USER_ID)
    response = anon_client.request(
        route.method,
        route.url,
        json=route.json_body,
        headers={"Authorization": f"Bearer {forged}"},
    )

    assert response.status_code == 401, (
        f"{route.id} answered {response.status_code} for a forged signature"
    )


@pytest.mark.parametrize("route", PROTECTED_ROUTES, ids=[r.id for r in PROTECTED_ROUTES])
def test_route_rejects_an_expired_token(anon_client, jwks, route):
    expired = jwks.factory.token(DEV_USER_ID, ttl_seconds=-60)
    response = anon_client.request(
        route.method,
        route.url,
        json=route.json_body,
        headers={"Authorization": f"Bearer {expired}"},
    )

    assert response.status_code == 401, (
        f"{route.id} answered {response.status_code} for an expired token"
    )


def test_the_coaching_websocket_is_not_a_public_upgrade(anon_client):
    """The WS route is absent from OpenAPI, so the guard above cannot see it.

    It is asserted here in the same spirit: no token, no socket (M11 removed
    both the ``?user_id=`` parameter and the dev-user fallback). The detailed
    handshake matrix lives in tests/test_ws.py.
    """
    from starlette.websockets import WebSocketDisconnect

    from app.modules.triggers.ws import WS_CLOSE_POLICY_VIOLATION

    with pytest.raises(WebSocketDisconnect) as refusal:
        with anon_client.websocket_connect(f"/api/v1/ws/coaching?user_id={DEV_USER_ID}"):
            pass

    assert refusal.value.code == WS_CLOSE_POLICY_VIOLATION
