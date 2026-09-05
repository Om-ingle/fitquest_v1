from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import settings (reads DATABASE_URL from the environment / .env files) and
# every SQLModel model so SQLModel.metadata is fully populated.
from app.core.config import settings
from app.modules.users.models import Friendship, User  # noqa: F401
from app.modules.map.models import HexOwnership  # noqa: F401
from app.modules.runs.models import CapturedHex, RunSession, UserDailyActivity  # noqa: F401
from app.modules.quests.models import Quest, UserQuest  # noqa: F401
from app.modules.rag.models import RagChunk, RagDocument  # noqa: F401

from sqlmodel import SQLModel

# Alembic Config object — provides access to values within alembic.ini.
config = context.config

# Use the application's DATABASE_URL (env/.env), not a URL baked into
# alembic.ini, so credentials never live in a tracked file. '%' must be
# escaped for configparser interpolation.
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a DB connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode with an Engine/connection."""
    connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
