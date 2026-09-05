from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings

# pool_pre_ping keeps long-lived connections healthy against a remote
# PostgreSQL (Supabase) that may drop idle connections.
engine = create_engine(settings.database_url, echo=False, pool_pre_ping=True)


def create_db_and_tables() -> None:
    """Dev/seed convenience only. The canonical schema source is Alembic —
    run `alembic upgrade head` (see apps/api/README.md)."""
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
