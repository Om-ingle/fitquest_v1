"""Shared test fixtures.

DATABASE_URL must be set before any app import (the app config has no
default). The tests run against a throwaway local SQLite file so they do
not need Supabase credentials; PostgreSQL connectivity is verified
separately by running the app/migrations against the real DATABASE_URL.
"""
import os

TEST_DB = "sqlite:///./test_fitquest.db"
os.environ.setdefault("DATABASE_URL", TEST_DB)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from app.core.database import engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    SQLModel.metadata.create_all(engine)
    with TestClient(app) as test_client:
        yield test_client
    SQLModel.metadata.drop_all(engine)
