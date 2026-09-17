"""M11 — JWKS-backed verification keys for Supabase access tokens.

Supabase signs access tokens with the project's asymmetric signing key
(ECDSA P-256 / ES256) and publishes the public half at
``{SUPABASE_URL}/auth/v1/.well-known/jwks.json``. The backend therefore holds
no signing secret at all: it fetches public keys and verifies signatures. A
leaked backend configuration cannot mint a token (F-04/F-12).

Why a cache rather than a fetch per request: the document changes only when a
key is rotated, and verification is on the hot path of every authenticated
call. An unknown ``kid`` forces exactly one refresh before failing, so a
rotation is honored immediately instead of waiting out the TTL.

Failure classification matters here, and there are three outcomes, not two:

* the document could not be obtained — [JwksUnavailable] (a 5xx, because a
  perfectly good token cannot be checked right now);
* the document was obtained but names no key matching the token — this is a
  [UnknownSigningKey], i.e. a token this project did not issue (a 401);
* the key was found and the signature decided the matter.

Lumping the first two together would either log every user out during an
identity-provider blip or invite a "fallback" that trusts an unverifiable
token — the exact shape of an auth bypass.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Bounded so a hanging identity provider cannot pin a worker thread.
JWKS_HTTP_TIMEOUT_SECONDS = 10.0

# Keys are identified by `kid`; this is the claim name in the JWKS document.
_KID = "kid"


class JwksUnavailable(RuntimeError):
    """The verification keys could not be obtained (network or configuration).

    Distinct from a bad token on purpose: callers must translate this into a
    5xx, never into a 401.
    """


class UnknownSigningKey(RuntimeError):
    """The token names a `kid` this project does not publish.

    The document was fetched successfully (including after a rotation-refresh),
    so this is not an outage — it is a token issued elsewhere, or forged. It
    maps to a 401, never to a 5xx.
    """


class JwksCache:
    """Thread-safe cache of the project's public signing keys, keyed by `kid`.

    The API is synchronous and FastAPI runs sync dependencies in a threadpool,
    so the lock (not an async primitive) is what makes a refresh single-flight:
    concurrent misses wait for the in-flight fetch instead of each opening one.
    """

    def __init__(self, ttl_seconds: float | None = None) -> None:
        # RLock: _refresh is reachable from get_key while the lock is held.
        self._lock = threading.RLock()
        self._ttl_override = ttl_seconds
        self._keys: dict[str, dict[str, Any]] = {}
        self._fetched_at: float = 0.0

    @property
    def _ttl_seconds(self) -> float:
        if self._ttl_override is not None:
            return self._ttl_override
        return settings.supabase_jwks_cache_seconds

    def get_key(self, kid: str | None) -> dict[str, Any]:
        """Return the JWK for `kid`, refreshing if the cache is stale or lacks it.

        Raises [JwksUnavailable] when the document cannot be obtained at all,
        and [UnknownSigningKey] when it was obtained but does not contain a
        matching key — never returns a placeholder or a "best guess" key.
        """
        with self._lock:
            if not self._is_fresh():
                self._refresh()
            key = self._select(kid)
            if key is None:
                # Either the signing key rotated since the cache was filled, or
                # the token names a key this project never published. One
                # refresh distinguishes the two; a second failure is terminal.
                self._refresh()
                key = self._select(kid)
            if key is None:
                raise UnknownSigningKey("no verification key matches this token")
            return key

    def clear(self) -> None:
        """Drop the cached document (tests, and rotation-driven diagnostics)."""
        with self._lock:
            self._keys = {}
            self._fetched_at = 0.0

    # ── internals (callers hold the lock) ─────────────────────────────────

    def _is_fresh(self) -> bool:
        return bool(self._keys) and (time.monotonic() - self._fetched_at) < self._ttl_seconds

    def _select(self, kid: str | None) -> dict[str, Any] | None:
        if kid:
            return self._keys.get(kid)
        # No `kid` in the header. Only unambiguous when the document holds a
        # single key; picking one of several would be a guess.
        if len(self._keys) == 1:
            return next(iter(self._keys.values()))
        return None

    def _refresh(self) -> None:
        url = settings.supabase_jwks_url
        if not url:
            raise JwksUnavailable("SUPABASE_URL is not configured")

        try:
            with httpx.Client(timeout=JWKS_HTTP_TIMEOUT_SECONDS) as client:
                response = client.get(url)
                response.raise_for_status()
                document = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Transport failure, non-2xx, or a body that is not JSON. The URL is
            # logged (it is public configuration); no token or credential is.
            logger.warning("JWKS refresh failed for %s: %s", url, type(exc).__name__)
            raise JwksUnavailable("could not reach the JWKS endpoint") from exc

        if not isinstance(document, dict):
            raise JwksUnavailable("JWKS document is not a JSON object")

        keys = {
            key[_KID]: key
            for key in document.get("keys", [])
            if isinstance(key, dict) and key.get(_KID)
        }
        if not keys:
            raise JwksUnavailable("JWKS document contained no usable keys")

        self._keys = keys
        self._fetched_at = time.monotonic()


# Process-wide cache. A module singleton (like the coach cache and the coaching
# session manager) so every request shares one document and one refresh.
jwks_cache = JwksCache()
