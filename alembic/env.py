"""Alembic migration environment for Tailor.

The connection URL and engine come from the application itself (app/db.py), which
is the single source of truth for how Tailor connects to its database. This means:
  * Alembic targets exactly the same database the app would.
  * No credentials live in alembic.ini -- they come from env vars / .env.
  * The same explicit LOCAL_DB opt-in works for local migration testing.
"""

from logging.config import fileConfig

from alembic import context

# Import the application's engine and metadata. Importing app.db resolves the
# database URL via _build_database_url(), which will raise a clear error if the
# database is not configured -- the same fail-loud behavior as the app.
from app.db import engine, Base
import app.models  # noqa: F401  (populate Base.metadata with all models)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a live connection)."""
    context.configure(
        url=str(engine.url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against the application's engine."""
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
