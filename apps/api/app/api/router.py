from fastapi import APIRouter

from app.modules.leaderboard import router as leaderboard_router
from app.modules.map import router as map_router
from app.modules.quests import router as quests_router
from app.modules.recommendations import router as recommendations_router
from app.modules.runs import router as runs_router
from app.modules.users import router as users_router

api_router = APIRouter()

api_router.include_router(users_router.router, prefix="/users", tags=["Users"])
api_router.include_router(map_router.router, prefix="/map", tags=["Map"])
api_router.include_router(runs_router.router, prefix="/runs", tags=["Runs"])
api_router.include_router(quests_router.router, prefix="/quests", tags=["Quests"])
api_router.include_router(leaderboard_router.router, prefix="/leaderboard", tags=["Leaderboard"])
api_router.include_router(recommendations_router.router, prefix="/recommendations", tags=["Recommendations"])
