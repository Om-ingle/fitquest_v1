"""Shared test fixtures.

DATABASE_URL must be set before any app import (the app config has no
default). The tests run against a throwaway local SQLite file so they do
not need Supabase credentials; PostgreSQL connectivity is verified
separately by running the app/migrations against the real DATABASE_URL.
"""
import os

TEST_DB = "sqlite:///./test_fitquest.db"
os.environ.setdefault("DATABASE_URL", TEST_DB)

# M8.3A — disable the real-time AI push stage for every test by default. The
# module singleton reads this at import; M8.3A tests re-enable it with fake
# providers/scheduler on purpose. A stray live push would otherwise pay real
# (or fake-but-unexpected) LLM calls whenever a trigger fires while a WebSocket
# session is open (e.g. the M8.2 integration tests).
os.environ.setdefault("PUSH_COACH_ENABLED", "false")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from app.core.database import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.coach.cache import coach_cache  # noqa: E402
from app.modules.coach.push import push_coach  # noqa: E402
from app.modules.triggers.engine import trigger_engine  # noqa: E402
from app.modules.triggers.ws import manager as coaching_ws_manager  # noqa: E402


@pytest.fixture()
def client():
    # The coach cache, trigger engine and coaching-WS session manager are
    # process-global singletons (shared by the routers/services); clear them
    # with the DB so cached responses / accepted triggers / live WS sessions
    # never leak across tests. The push coach is likewise disabled + reset so
    # no background AI generation leaks between tests.
    coach_cache.clear()
    trigger_engine.clear()
    coaching_ws_manager.clear()
    push_coach.reset()
    push_coach.enabled = False
    SQLModel.metadata.create_all(engine)
    with TestClient(app) as test_client:
        yield test_client
    SQLModel.metadata.drop_all(engine)
    coach_cache.clear()
    trigger_engine.clear()
    coaching_ws_manager.clear()
    push_coach.reset()
    push_coach.enabled = False
