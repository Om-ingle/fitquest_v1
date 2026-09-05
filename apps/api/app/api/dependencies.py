from fastapi import Depends
from sqlmodel import Session

from app.core.database import get_session

# ── Database ──────────────────────────────────────────────────────────────────

def get_db(session: Session = Depends(get_session)) -> Session:
    return session


# ── Auth ──────────────────────────────────────────────────────────────────────
# DEV MODE: The backend runs against Supabase PostgreSQL, but authentication is
# deferred (see SRS §4.2). All endpoints return a fixed dev user so the Android
# app works without any real login flow.
#
# TODO(production): Replace this stub with real Supabase JWT validation:
#   from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
#   from app.core.security import decode_supabase_jwt
#   bearer_scheme = HTTPBearer(auto_error=False)
#   def get_current_user(credentials = Depends(bearer_scheme)):
#       payload = decode_supabase_jwt(credentials.credentials)
#       return {"id": str(payload["sub"])}

DEV_USER_ID = "00000000-0000-0000-0000-000000000001"

def get_current_user() -> dict[str, str]:
    """Dev stub — returns a fixed user. Replace with real auth in production."""
    return {"id": DEV_USER_ID}
