"""Fix E — deterministic context fingerprint + user-scoped coach cache.

WHY (see Fix E spec part 2): Home → Profile → Home used to re-call
GET /api/v1/coach and pay for a full LLM generation even when nothing the
coach cares about had changed. The rule now is:

    same user + same context fingerprint  → serve the stored CoachResponse
    changed context fingerprint           → full pipeline, then store

The fingerprint is deterministic over the REAL ``FitnessContext`` used for
generation, so caching is invalidated by data changes — never by time,
navigation, or a recompose. A version tag rides inside the digest, so
changing which fields feed the fingerprint (or their semantics) invalidates
every stale entry on the next deploy.

Cache-safety (Fix E part 3): keys are scoped per ``user_id``, a stored
response is only ever returned to the SAME user, and every returned object
carries its own full context + recommendation + retrieval metadata plus
``context_fingerprint`` and ``cached``, so a served response is always
auditable. Nothing here touches credentials or RAG content.

In-process on purpose: the app is a single-instance dev backend, and this
module has one narrow seam (``CoachCache``) that a Redis-backed
implementation can replace later without touching the service or router
(SRS §17 treats Redis as optional).
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from collections import OrderedDict

from app.modules.coach.schemas import CoachResponse

# Bump when the fingerprint's input field set/semantics change — every
# cached entry from before the change stops matching immediately.
FINGERPRINT_VERSION = "fix-e-v1"

# Bounded cache: one entry per user, LRU-evicted past this many users.
MAX_CACHED_USERS = 200


def context_fingerprint(context) -> str:
    """Deterministic digest of the context a generation was grounded in.

    The serialization is canonical (sorted keys, compact separators), so
    the same context always hashes to the same fingerprint. Adding a field
    to ``FitnessContext`` automatically changes the digest — entries from
    before a schema change are simply misses, never wrong hits.
    """
    payload = {
        "version": FINGERPRINT_VERSION,
        # model_dump(mode="json") turns UUID/date/datetime into strings and
        # drops nothing; the keyset == the schema's field set.
        **context.model_dump(mode="json"),
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CoachCache:
    """Per-user in-process cache of completed coaching generations.

    One entry per user, keyed by the fingerprint of the context that
    produced it. Thread-safe (the endpoint runs in FastAPI's threadpool);
    each store/get holds a short global lock. The expensive LLM/RAG work
    happens OUTSIDE the lock, so one slow generation never blocks another
    user.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # user_id(str) -> OrderedDict(fingerprint -> CoachResponse); the
        # OrderedDict gives us cheap LRU eviction by move_to_end.
        self._entries: OrderedDict[str, OrderedDict[str, CoachResponse]] = OrderedDict()

    def get_cached(self, user_id: uuid.UUID, fingerprint: str) -> CoachResponse | None:
        """Return the stored response for this user IF its generation
        fingerprint matches (otherwise None → the caller regenerates)."""
        key = str(user_id)
        with self._lock:
            user_entries = self._entries.get(key)
            if user_entries is None:
                return None
            cached = user_entries.get(fingerprint)
            if cached is None:
                return None
            user_entries.move_to_end(fingerprint)
            self._entries.move_to_end(key)
            return cached

    def store(self, user_id: uuid.UUID, fingerprint: str, response: CoachResponse) -> None:
        """Record a completed generation under its context fingerprint.

        Bounded: exceeds MAX_CACHED_USERS, the least-recently-used user is
        evicted (only ever an extra future generation — never wrong data).
        """
        key = str(user_id)
        with self._lock:
            user_entries = self._entries.get(key)
            if user_entries is None:
                user_entries = OrderedDict()
                self._entries[key] = user_entries
            user_entries[fingerprint] = response
            user_entries.move_to_end(fingerprint)
            self._entries.move_to_end(key)
            while len(self._entries) > MAX_CACHED_USERS:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


# Module singleton handed to the router so every HTTP request shares one
# cache; direct-service tests pass their own (or None) to stay isolated.
coach_cache = CoachCache()
