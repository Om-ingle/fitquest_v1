from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.modules.triggers.ws import router as coaching_ws_router

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)

# M11 — the coaching WebSocket is mounted here rather than on `api_router`.
# FastAPI copies a router's `dependencies` onto its websocket routes, and the
# REST auth dependency (HTTPBearer) cannot read a WS handshake; mounting it
# here keeps it clear of that dependency while preserving the exact path
# `/api/v1/ws/coaching`. The endpoint authenticates its own handshake header.
app.include_router(
    coaching_ws_router,
    prefix=f"{settings.api_v1_prefix}/ws",
    tags=["Coaching WS"],
)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "message": "FitQuest Backend is running."}
