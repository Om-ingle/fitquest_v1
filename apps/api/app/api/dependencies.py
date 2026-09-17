import logging
import uuid

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

from app.core.config import settings
from app.core.database import get_session
from app.core.jwks import JwksUnavailable
from app.core.security import InvalidTokenError, decode_supabase_jwt
from app.modules.users.service import resolve_or_provision_user

logger = logging.getLogger(__name__)

# ── Database ──────────────────────────────────────────────────────────────────

def get_db(session: Session = Depends(get_session)) -> Session:
    return session


# ── Auth (M11 / F-04) ─────────────────────────────────────────────────────────
# Real bearer authentication. Identity comes from the verified token's `sub`
# claim and from nowhere else — no header, path, query parameter or request body
# may name the acting user. Domain modules are unchanged: they keep reading
# `current_user["id"]`, which is the INTERNAL user UUID (see users/models.py for
# why the internal id and the external subject are kept distinct).

DEV_USER_ID = "00000000-0000-0000-0000-000000000001"
"""Seeded development/test user — see apps/api/seed.py.

It exists so a local database has an owner for its data and so tests have a
stable identity; it is provisioned explicitly by the seed script, which is the
only thing that grants it an `auth_subject`. It is NOT a fallback: no request
without a valid token is ever served as this user, no real account is mapped
onto this id, and its existing rows are never reassigned. In production it is
unreachable by construction — Supabase Auth, the only issuer whose tokens
verify, has no account with this UUID.
"""

# auto_error=False so a missing/malformed Authorization header reaches our own
# 401 with a WWW-Authenticate challenge, instead of FastAPI's bare 403.
bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=403, detail=detail)


def bearer_token_from_headers(headers) -> str | None:
    """Extract a bearer token from a raw header mapping, or None.

    Shared by the HTTP dependency (via HTTPBearer) and the coaching WebSocket,
    which has no HTTPBearer equivalent: a WebSocket handshake carries headers
    too, and per the M11 WebSocket decision the token travels THERE rather than
    in the query string, where it would land in access logs, proxies and
    browser history.
    """
    raw = headers.get("authorization") or ""
    scheme, _, token = raw.partition(" ")
    if scheme.strip().lower() != "bearer":
        return None
    return token.strip() or None


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Resolve the acting user from a verified Supabase access token.

    Returns the identity every domain module already consumes:
    ``{"id": <internal user uuid>, "subject": <supabase auth.users.id>}``.
    """
    if credentials is None or not credentials.credentials.strip():
        raise _unauthorized("Not authenticated")

    try:
        payload = decode_supabase_jwt(credentials.credentials)
    except InvalidTokenError as exc:
        # The message is fixed on purpose: verification failures are not
        # distinguished for the caller, and the token is never logged.
        raise _unauthorized("Invalid or expired token") from exc
    except JwksUnavailable as exc:
        # The token may be perfectly valid — we simply cannot check it. A 401
        # here would log every user out during an identity-provider blip.
        logger.error("JWKS unavailable while verifying a bearer token")
        raise HTTPException(
            status_code=503,
            detail="Authentication temporarily unavailable",
        ) from exc

    subject = str(payload.get("sub") or "").strip()
    if not subject:
        # `require_sub` makes this unreachable through jwt.decode; kept as a
        # guard so a future decode change cannot silently yield an anonymous id.
        raise _unauthorized("Invalid or expired token")

    user = resolve_or_provision_user(db, subject=subject, claims=payload)
    return {"id": str(user.id), "subject": subject}


def require_own_identity(
    user_id: uuid.UUID,
    current_user: dict[str, str] = Depends(get_current_user),
) -> dict[str, str]:
    """Authorize a route whose PATH names the acting user.

    Authentication alone is not isolation. ``PATCH /users/{user_id}`` is
    perfectly authenticated for any logged-in account and still lets that
    account edit every other account; the token would be verified and the
    request would be authorized as the wrong person. This dependency rejects a
    path identity that is not the token identity, so identity keeps coming from
    exactly one place.

    403 rather than 404: the path names the caller's own claim about who they
    are, and the honest answer is "that is not you".
    """
    if str(user_id) != current_user["id"]:
        raise _forbidden("You may only act on your own account")
    return current_user


def require_admin(
    current_user: dict[str, str] = Depends(get_current_user),
) -> dict[str, str]:
    """Authorize a privileged route against the ADMIN_USER_IDS allow-list.

    Keyed on the verified token SUBJECT (``auth.users.id``), not the internal
    user id: the subject is what an operator reads off the identity provider,
    and an internal id is regenerated if a database is rebuilt. Empty
    ADMIN_USER_IDS therefore means nobody, which is the correct default for the
    privileged write (F-18 knowledge-base ingestion).
    """
    if current_user["subject"] not in settings.admin_user_id_set:
        raise _forbidden("Administrator access required")
    return current_user
