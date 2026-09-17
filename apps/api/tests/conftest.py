"""Shared test fixtures.

DATABASE_URL must be set before any app import (the app config has no
default). The tests run against a throwaway local SQLite file so they do
not need Supabase credentials; PostgreSQL connectivity is verified
separately by running the app/migrations against the real DATABASE_URL.

M11 — authentication is REAL in tests, not stubbed
--------------------------------------------------
Since every ``/api/v1`` route now requires a verified bearer token, the shared
``client`` fixture authenticates as the seeded development user. That is not a
convenience: it is what makes the existing behavioural tests still meaningful.
A test suite that bypasses auth would stop covering the thing M11 added.

Three fixtures carry it:

* ``es256_key`` / ``foreign_key`` — real P-256 keypairs (tests/authkit.py).
* ``jwks`` — installs the trusted key as the document the app verifies against,
  and hands out the token factory.
* ``client`` — authenticated as ``DEV_USER_ID``; ``anon_client`` — no token at
  all, for the unauthenticated-access tests; ``other_client`` — a second,
  independent account, for the isolation tests.

Auth is never disabled. The only thing patched is the JWKS *fetch*, so no test
talks to the network; signature verification, claim checks and identity
resolution all run for real.

AI provider credentials are another matter: they are *emptied* below rather
than patched, so the suite cannot borrow a developer's real key from .env. See
the note at the neutralisation block for why that is the difference between a
hermetic suite and one that merely happens to be run on a hermetic machine.
"""
import os

TEST_DB = "sqlite:///./test_fitquest.db"
os.environ.setdefault("DATABASE_URL", TEST_DB)

# M11 — forced, not setdefault'd: a test run must never inherit a developer's
# real Supabase project, or a token meant for the fixture keys could be checked
# against production JWKS. ENVIRONMENT=test is a development value, so the
# fail-fast config check stays relaxed here.
os.environ["SUPABASE_URL"] = "https://test-project.supabase.co"
os.environ["ENVIRONMENT"] = "test"

# M11 — the admin allow-list is empty by default, so the privileged routes are
# closed unless a test opens them deliberately (see the `admin` fixture).
os.environ["ADMIN_USER_IDS"] = ""

# AI providers — forced to empty, not setdefault'd, so hermeticity is a
# property of the SUITE and not merely of the machine it runs on.
#
# Settings loads `env_file=(".env", "../../.env")`, so a developer's own
# apps/api/.env silently configures a real provider for the whole suite.
# Environment variables outrank the dotenv file in pydantic-settings, so
# writing these here (before `app.core.config` is imported) empties the
# credential the .env would have supplied. `get_embedding_provider` and
# `get_llm_provider` test their key for truthiness, so an empty string is
# "not configured" and the route answers 503 rather than calling out.
#
# This is what makes the previous failure mode impossible instead of merely
# absent: the coach test that once passed locally by making a real, billable
# LLM call was passing *because* of a developer's key, and would have kept
# doing so — invisibly — until it ran on a runner without one. With the
# credentials removed here that test cannot borrow a key from anywhere, so it
# fails on the developer's machine too, which is where a failure is cheap.
# No test needs a real provider: the ones that exercise those routes install
# deterministic fakes (see tests/test_coach_api.py::_patch_providers).
#
# SUPABASE_SECRET_KEY is included because it is a secret no test uses; leaving
# it visible would let a future test reach production Supabase by accident.
for _var in (
    "GEMINI_API_KEY",
    "AGENTIC_API_KEY",
    "AGENT_ROUTER_API_KEY",
    "SUPABASE_SECRET_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
):
    os.environ[_var] = ""

# Pinned so the provider branch is deterministic: with AGENTIC_API_KEY empty
# the agentrouter branch would raise either way, but LLM_PROVIDER=gemini makes
# it the Gemini branch's "not configured" that is exercised, which is the one
# a developer without credentials sees.
os.environ["LLM_PROVIDER"] = "gemini"

# M8.3A — disable the real-time AI push stage for every test by default. The
# module singleton reads this at import; M8.3A tests re-enable it with fake
# providers/scheduler on purpose. A stray live push would otherwise pay real
# (or fake-but-unexpected) LLM costs whenever a trigger fires while a WebSocket
# session is open (e.g. the M8.2 integration tests).
os.environ.setdefault("PUSH_COACH_ENABLED", "false")

import contextlib  # noqa: E402
import uuid  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, SQLModel  # noqa: E402

from app.api.dependencies import DEV_USER_ID  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.database import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.coach.cache import coach_cache  # noqa: E402
from app.modules.coach.push import push_coach  # noqa: E402
from app.modules.triggers.engine import trigger_engine  # noqa: E402
from app.modules.triggers.ws import manager as coaching_ws_manager  # noqa: E402
from tests.authkit import (  # noqa: E402
    TRUSTED_KID,
    Es256Key,
    TokenFactory,
    install_jwks,
    link_identity,
)

# The subject the seeded development user answers to. seed.py grants a seeded
# row its OWN id as its subject; tests follow the same convention (see
# authkit.link_identity) so the two never drift apart.
DEV_USER_SUBJECT = DEV_USER_ID

# A second, independent account — the "other user" in the isolation tests. Its
# id is deliberately NOT adjacent to DEV_USER_ID so a mix-up is obvious.
OTHER_USER_ID = "00000000-0000-4000-8000-00000000c0de"
OTHER_USER_SUBJECT = OTHER_USER_ID


@pytest.fixture(scope="session")
def es256_key() -> Es256Key:
    """The trusted signing key. Its public half is the JWKS document."""
    return Es256Key(TRUSTED_KID)


@pytest.fixture(scope="session")
def foreign_key() -> Es256Key:
    """A key the app never publishes — the forgery case."""
    return Es256Key("fitquest-test-es256-untrusted")


@pytest.fixture()
def tokens(es256_key: Es256Key) -> TokenFactory:
    return TokenFactory(es256_key)


@pytest.fixture()
def jwks(monkeypatch, es256_key: Es256Key, foreign_key: Es256Key, tokens: TokenFactory):
    """Install the trusted key as the app's verification key set.

    Returns an object carrying everything a test needs: the token factory and
    both keys, so a test can sign with the wrong one on purpose.
    """
    install_jwks(monkeypatch, [es256_key])

    class _Jwks:
        trusted = es256_key
        foreign = foreign_key
        factory = tokens
        subject = DEV_USER_SUBJECT

    return _Jwks


@contextlib.contextmanager
def _running_client(headers: dict[str, str], identities: list[tuple[str, str]] = ()):
    """A TestClient over a freshly created schema, with the default headers.

    The coach cache, trigger engine and coaching-WS session manager are
    process-global singletons (shared by the routers/services); clear them with
    the DB so cached responses / accepted triggers / live WS sessions never leak
    across tests. The push coach is likewise disabled + reset so no background
    AI generation leaks between tests.

    ``identities`` are extra accounts to create and link. They are created
    AFTER the schema exists — a row cannot be inserted into a table that has
    not been created yet.
    """
    coach_cache.clear()
    trigger_engine.clear()
    coaching_ws_manager.clear()
    push_coach.reset()
    push_coach.enabled = False
    SQLModel.metadata.create_all(engine)
    # The dev user must exist as a row linked to its subject, exactly as
    # seed.py leaves it: the first authenticated request resolves by subject,
    # so a row without one would be invisible and provisioning would create a
    # second, unrelated account.
    link_identity(DEV_USER_ID, "devuser")
    for user_id, username in identities:
        link_identity(user_id, username)
    try:
        with TestClient(app, headers=headers) as test_client:
            yield test_client
    finally:
        SQLModel.metadata.drop_all(engine)
        coach_cache.clear()
        trigger_engine.clear()
        coaching_ws_manager.clear()
        push_coach.reset()
        push_coach.enabled = False


@pytest.fixture()
def client(jwks):
    """The default client: authenticated as the seeded development user.

    Requests made through it carry a real, verifiable ES256 token, so every
    existing endpoint test exercises the authenticated path it will see in
    production.
    """
    with _running_client(jwks.factory.headers(DEV_USER_SUBJECT)) as test_client:
        yield test_client


@pytest.fixture()
def anon_client(jwks):
    """Same app, same schema — but no Authorization header at all."""
    with _running_client({}) as test_client:
        yield test_client


@pytest.fixture()
def other_client(jwks):
    """A second independent account, for cross-user isolation tests.

    The row is created and linked to its own subject BEFORE the client issues
    any request, so the first call resolves to an existing account rather than
    provisioning one on the fly.
    """
    with _running_client(
        jwks.factory.headers(OTHER_USER_SUBJECT),
        identities=[(OTHER_USER_ID, "otheruser")],
    ) as test_client:
        yield test_client


@pytest.fixture()
def other_headers(jwks):
    """The second account's Authorization header, for a SHARED schema.

    ``other_client`` stands up its own schema, which cannot be nested inside
    another client's (each tears the tables down on exit). Isolation tests need
    two identities against ONE schema, and on a real deployment two accounts are
    just two tokens against the same server — so the second account is reached
    by overriding the Authorization header per request, which is exactly how it
    works in production.

    The row is created here, after the schema exists, rather than at fixture
    setup time.
    """
    link_identity(OTHER_USER_ID, "otheruser")
    return jwks.factory.headers(OTHER_USER_SUBJECT)


@pytest.fixture()
def other_user_id() -> uuid.UUID:
    return uuid.UUID(OTHER_USER_ID)


@pytest.fixture()
def admin(monkeypatch):
    """Open the ADMIN_USER_IDS allow-list to the acting test account.

    Reassigns the field on the live settings object, so it covers the admin
    gate wherever it is read (it is read per request, not cached at import).
    """
    monkeypatch.setattr(settings, "admin_user_ids", DEV_USER_SUBJECT)
    return DEV_USER_SUBJECT
