"""M11 — Supabase access-token verification (F-04).

Replaces the dormant HS256 stub. The shape of the change is not cosmetic: the
previous implementation verified a *shared secret* that this project does not
have and never configured, so it could neither validate a real Supabase token
nor be safely enabled (its default secret was the literal string
``change-me``). Verification is now asymmetric:

* algorithm is pinned to ES256 — the algorithm Supabase actually publishes for
  this project (`kty=EC`) — which also closes the algorithm-confusion class
  where a token header names a cheaper algorithm than the key supports;
* the signature is checked against the project's public key, looked up by
  ``kid`` in the JWKS document, so no secret exists in the backend at all;
* ``aud`` and ``iss`` are verified rather than skipped. A token minted for a
  different audience, or by a different project, must not authenticate here;
* ``exp`` and ``sub`` are required, so an eternal token or a subjectless one
  cannot pass.

Nothing in this module logs a token. Failures carry a fixed message, because a
verification error message is itself an oracle.
"""

from __future__ import annotations

from typing import Any

from jose import JWTError, jwt

from app.core.config import settings
from app.core.jwks import UnknownSigningKey, jwks_cache

# Only ES256. Supabase's asymmetric project keys are ECDSA P-256; no HS256
# fallback exists by decision (D2) — a shared-secret path would reintroduce
# exactly the forgery risk this milestone removes.
ALGORITHMS = ["ES256"]

# Supabase marks end-user access tokens with this audience. Service-role keys
# and other token kinds must not authenticate as a FitQuest user.
EXPECTED_AUDIENCE = "authenticated"


class InvalidTokenError(ValueError):
    """The token is malformed, expired, or not valid for this project.

    Distinct from [app.core.jwks.JwksUnavailable]: this is a client error
    (401), whereas an unobtainable key is a server error (503).
    """


def decode_supabase_jwt(token: str) -> dict[str, Any]:
    """Verify a Supabase access token and return its claims.

    Raises [InvalidTokenError] for a bad token and
    [app.core.jwks.JwksUnavailable] when the verification keys cannot be
    obtained — callers must map the two to different status codes.
    """
    try:
        # Unverified read of the header ONLY to learn which key to fetch. The
        # `kid` is untrusted input used as a cache lookup key; nothing is
        # trusted until jwt.decode verifies the signature below.
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise InvalidTokenError("Token is not a valid JWT") from exc

    try:
        key = jwks_cache.get_key(header.get("kid"))
    except UnknownSigningKey as exc:
        # The key set was read successfully and this token's key is not in it,
        # so the token was issued by something other than this project. A 401 —
        # an outage would have surfaced as JwksUnavailable instead.
        raise InvalidTokenError("Invalid or expired token") from exc

    try:
        return jwt.decode(
            token,
            key,
            algorithms=ALGORITHMS,
            audience=EXPECTED_AUDIENCE,
            issuer=settings.supabase_jwt_issuer,
            options={"require_exp": True, "require_sub": True},
        )
    except JWTError as exc:
        raise InvalidTokenError("Invalid or expired token") from exc
