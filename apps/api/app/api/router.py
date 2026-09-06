from fastapi import APIRouter

from app.modules.coach import router as coach_router
from app.modules.leaderboard import router as leaderboard_router
from app.modules.map import router as map_router
from app.modules.quests import router as quests_router
from app.modules.rag import router as rag_router
from app.modules.recommendations import router as recommendations_router
from app.modules.runs import router as runs_router
from app.modules.triggers.ws import router as coaching_ws_router
from app.modules.users import router as users_router

# M8.3A — real-time AI push. Importing the module is the wiring: it registers
# the PushCoach singleton as a trigger-engine subscriber ONCE, at import,
# exactly like the M8.2 WebSocket transport. The engine stays the producer.
from app.modules.coach.push import push_coach as _push_coach  # noqa: F401

api_router = APIRouter()

api_router.include_router(users_router.router, prefix="/users", tags=["Users"])
api_router.include_router(map_router.router, prefix="/map", tags=["Map"])
api_router.include_router(runs_router.router, prefix="/runs", tags=["Runs"])
api_router.include_router(quests_router.router, prefix="/quests", tags=["Quests"])
api_router.include_router(leaderboard_router.router, prefix="/leaderboard", tags=["Leaderboard"])
api_router.include_router(recommendations_router.router, prefix="/recommendations", tags=["Recommendations"])
api_router.include_router(rag_router.router, prefix="/rag", tags=["RAG"])
api_router.include_router(coach_router.router, prefix="/coach", tags=["Coach"])
# M8.2 — real-time coaching channel (WebSocket), an ADDITION to REST (SRS §16).
# Mounted under /ws so the endpoint is /api/v1/ws/coaching.
api_router.include_router(coaching_ws_router, prefix="/ws", tags=["Coaching WS"])
