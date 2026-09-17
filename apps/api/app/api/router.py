from fastapi import APIRouter, Depends

from app.api.dependencies import get_current_user
from app.modules.coach import router as coach_router
from app.modules.leaderboard import router as leaderboard_router
from app.modules.map import router as map_router
from app.modules.quests import router as quests_router
from app.modules.rag import router as rag_router
from app.modules.recommendations import router as recommendations_router
from app.modules.runs import router as runs_router
from app.modules.users import router as users_router

# M8.3A — real-time AI push. Importing the module is the wiring: it registers
# the PushCoach singleton as a trigger-engine subscriber ONCE, at import,
# exactly like the M8.2 WebSocket transport. The engine stays the producer.
from app.modules.coach.push import push_coach as _push_coach  # noqa: F401

# M11 — DEFAULT DENY. The auth dependency is attached to the router rather than
# to each route so a new endpoint cannot be left public by omission: anything
# mounted here requires a verified bearer token, and the only public route in
# the service is the app-level `/health`.
#
# Routes naming the acting user in their PATH need more than this and say so
# themselves — see `require_own_identity` in app/api/dependencies.py.
#
# NOT mounted here: the coaching WebSocket. FastAPI copies a router's
# `dependencies` onto its websocket routes too (fastapi/routing.py,
# `add_api_websocket_route`), and HTTPBearer has no credentials to read from a
# WS handshake — it would fail the connection for the wrong reason. That
# endpoint authenticates its own handshake header and is included directly on
# the app (see app/main.py), which keeps its path identical.
api_router = APIRouter(dependencies=[Depends(get_current_user)])

api_router.include_router(users_router.router, prefix="/users", tags=["Users"])
api_router.include_router(map_router.router, prefix="/map", tags=["Map"])
api_router.include_router(runs_router.router, prefix="/runs", tags=["Runs"])
api_router.include_router(quests_router.router, prefix="/quests", tags=["Quests"])
api_router.include_router(leaderboard_router.router, prefix="/leaderboard", tags=["Leaderboard"])
api_router.include_router(recommendations_router.router, prefix="/recommendations", tags=["Recommendations"])
api_router.include_router(rag_router.router, prefix="/rag", tags=["RAG"])
api_router.include_router(coach_router.router, prefix="/coach", tags=["Coach"])
