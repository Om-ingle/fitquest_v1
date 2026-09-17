"""M11 — durable ES256 test identity.

Real bearer authentication means tests need real tokens, and a token can only
be real if it is signed. This module builds a throwaway P-256 keypair, publishes
its public half as the JWKS document the app fetches, and signs access tokens
with it — so the verification path exercised in tests is the same one
production runs: ES256 signature → JWKS key lookup by ``kid`` → ``exp`` / ``aud``
/ ``iss`` / ``sub``.

Nothing here is a stub or a bypass. A test token is a genuine ES256 JWT; it is
only "test" in that its private key never leaves this process. That is what
makes the rejection cases meaningful: an expired token, a token for another
audience, or a token signed by a key the JWKS does not publish are refused by
the real verifier, not by a mock.

Key material is generated per session and never written to disk. No secret is
involved anywhere — the backend holds only public keys (F-04/F-12).
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jose import jwt
from sqlmodel import Session

from app.core.config import settings
from app.core.database import engine
from app.core.jwks import JwksCache, JwksUnavailable, jwks_cache
from app.modules.users.models import User

# Distinct `kid`s so the two keys below are never confusable.
TRUSTED_KID = "fitquest-test-es256"
FOREIGN_KID = "fitquest-test-es256-foreign"

# Supabase's audience for end-user access tokens — the value the backend
# requires. Kept here so a test can override it and prove the check is live.
EXPECTED_AUDIENCE = "authenticated"

# One hour: long enough that no test races it, short enough to be obviously
# a deliberate lifetime rather than "no expiry".
DEFAULT_TTL_SECONDS = 3600


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_json(payload: dict[str, Any]) -> str:
    return _b64u_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def _coordinate(value: int) -> str:
    """Encode a P-256 coordinate as JWK base64url (fixed 32-byte width)."""
    return _b64u_encode(value.to_bytes(32, byteorder="big"))


class Es256Key:
    """A P-256 keypair and the public JWK that verifies what it signs."""

    def __init__(self, kid: str) -> None:
        self.kid = kid
        self._private = ec.generate_private_key(ec.SECP256R1())
        self._private_pem = self._private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")

        numbers = self._private.public_key().public_numbers()
        self.jwk: dict[str, Any] = {
            "kty": "EC",
            "crv": "P-256",
            "alg": "ES256",
            "use": "sig",
            "kid": kid,
            "x": _coordinate(numbers.x),
            "y": _coordinate(numbers.y),
        }

    def sign(
        self,
        claims: dict[str, Any],
        *,
        kid: str | None = None,
        algorithm: str = "ES256",
    ) -> str:
        """Sign ``claims``. ``kid`` overrides the header so a test can present
        this key under another key's identity (a signature mismatch)."""
        return jwt.encode(
            claims,
            self._private_pem,
            algorithm=algorithm,
            headers={"kid": kid or self.kid, "typ": "JWT"},
        )


class TokenFactory:
    """Mints test access tokens, with every claim controllable.

    Defaults produce a token the backend MUST accept (right issuer, right
    audience, unexpired, with a subject). Each override exists so a test can
    flip exactly one thing and prove the verifier notices.
    """

    def __init__(self, key: Es256Key, *, issuer: str | None = None) -> None:
        self._key = key
        # The issuer the app actually verifies against — derived from
        # SUPABASE_URL, never invented here. A token minted against a made-up
        # issuer would be rejected for the wrong reason and the test would pass
        # while proving nothing.
        self.issuer = issuer or settings.supabase_jwt_issuer
        if self.issuer is None:  # pragma: no cover - conftest sets SUPABASE_URL
            raise RuntimeError(
                "SUPABASE_URL is not configured, so there is no issuer to mint "
                "tokens against; tests/conftest.py should have set it"
            )

    def claims(
        self,
        subject: str | uuid.UUID,
        *,
        email: str | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        **overrides: Any,
    ) -> dict[str, Any]:
        now = int(time.time())
        claims: dict[str, Any] = {
            "sub": str(subject),
            "aud": EXPECTED_AUDIENCE,
            "iss": self.issuer,
            "iat": now,
            "exp": now + ttl_seconds,
            "role": "authenticated",
        }
        if email is not None:
            claims["email"] = email
        claims.update(overrides)
        return claims

    def token(self, subject: str | uuid.UUID, **overrides: Any) -> str:
        return self._key.sign(self.claims(subject, **overrides))

    def headers(self, subject: str | uuid.UUID, **overrides: Any) -> dict[str, str]:
        """A ready-to-use Authorization header for ``subject``."""
        return {"Authorization": f"Bearer {self.token(subject, **overrides)}"}

    # ── deliberately-broken tokens ──────────────────────────────────────────

    def foreign_token(self, foreign_key: Es256Key, subject: str, **overrides: Any) -> str:
        """A well-formed token signed by a key this project does not publish.

        ``kid`` is left as the foreign key's own, so the JWKS lookup fails —
        the "unknown kid" path. Pass ``kid=TRUSTED_KID`` to instead present it
        as the trusted key, which fails at the signature check.
        """
        return foreign_key.sign(self.claims(subject, **overrides))

    def unsigned_token(self, subject: str, **overrides: Any) -> str:
        """``alg: none`` — the classic algorithm-confusion attempt.

        Hand-built because the signing libraries refuse to produce it, which is
        the point: the verifier must refuse to consume it.
        """
        header = _b64u_json({"alg": "none", "typ": "JWT"})
        payload = _b64u_json(self.claims(subject, **overrides))
        return f"{header}.{payload}."

    def hs256_token(self, subject: str, secret: str, **overrides: Any) -> str:
        """A token signed HS256 with a shared secret.

        M11 has no HS256 fallback (decision D2), and the secret the old code
        defaulted to is public knowledge. This exists so that claim is tested
        rather than asserted.
        """
        return jwt.encode(
            self.claims(subject, **overrides),
            secret,
            algorithm="HS256",
            headers={"kid": TRUSTED_KID, "typ": "JWT"},
        )


def install_jwks(monkeypatch, keys: list[Es256Key] | Exception) -> None:
    """Point the app's JWKS cache at ``keys`` (or at a failure).

    ``_refresh`` is the cache's single boundary with the outside world: it is
    what fetches and parses the document. Replacing it keeps every other part
    of the path real — freshness, the stale-refresh, the rotation re-fetch on
    an unknown ``kid``, and the UnknownSigningKey decision — while removing the
    network from the test.

    Pass an exception instance (e.g. ``JwksUnavailable("down")``) to model an
    identity-provider outage.
    """
    if isinstance(keys, Exception):
        failure = keys

        def _refresh(self) -> None:  # noqa: ANN001 - patched onto the class
            raise failure

    else:

        def _refresh(self) -> None:  # noqa: ANN001 - patched onto the class
            self._keys = {key.kid: key.jwk for key in keys}
            self._fetched_at = time.monotonic()

    monkeypatch.setattr(JwksCache, "_refresh", _refresh)
    jwks_cache.clear()


def jwks_outage() -> JwksUnavailable:
    """A representative outage, for ``install_jwks(monkeypatch, jwks_outage())``."""
    return JwksUnavailable("test: JWKS endpoint unreachable")


def link_identity(user_id: str | uuid.UUID, username: str) -> None:
    """Create (or link) a user row whose subject IS its own id.

    This mirrors exactly what ``seed.py`` does for the development/test users
    and is the established test convention for a second account: the subject is
    the row's own UUID and nothing else, so no real Supabase identity is
    silently mapped onto a row (decision D4). Idempotent.
    """
    with Session(engine) as session:
        user = session.get(User, uuid.UUID(str(user_id)))
        if user is None:
            session.add(
                User(
                    id=uuid.UUID(str(user_id)),
                    username=username,
                    auth_subject=str(user_id),
                )
            )
        elif user.auth_subject != str(user_id):
            user.auth_subject = str(user_id)
            session.add(user)
        session.commit()


def ensure_user(user_id: str | uuid.UUID, username: str, **fields: Any) -> None:
    """Get-or-create the row for ``user_id`` and apply ``fields`` to it.

    M11: the authenticated account now exists BEFORE a test body runs (conftest
    links the seeded dev user so requests can authenticate at all). A test that
    wants that account to carry particular stats must therefore UPDATE it —
    inserting a second row under the same primary key, or a second account
    under the same username, is a collision. This is also safe for a fresh id,
    so it replaces both the guard-style and the blind-insert seed helpers.
    """
    with Session(engine) as session:
        user = session.get(User, uuid.UUID(str(user_id)))
        if user is None:
            user = User(
                id=uuid.UUID(str(user_id)),
                username=username,
                auth_subject=str(user_id),
            )
            session.add(user)
        for key, value in fields.items():
            setattr(user, key, value)
        session.commit()


def user_row(user_id: str | uuid.UUID) -> User | None:
    """Read a user row directly, for assertions the API cannot make (e.g.
    "the subject was never linked", "the internal id did not change")."""
    with Session(engine) as session:
        return session.get(User, uuid.UUID(str(user_id)))
