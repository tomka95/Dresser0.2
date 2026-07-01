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


# Manual backup tables (e.g. `backup_clothing_items_20260615`) get created out-of-band
# during ops work. They have no ORM counterpart, so autogenerate / `alembic check`
# would reflect them and propose DROP TABLE. Anything named backup_* is operator-owned
# and must be invisible to autogenerate — filtered by prefix in BOTH hooks below.
_BACKUP_TABLE_PREFIX = "backup_"


def _include_name(name, type_, parent_names):
    """Exclude reflected backup_* tables from autogenerate / `alembic check`.

    include_name is the hook that sees names present in the DB but ABSENT from the ORM
    metadata (exactly how a backup_* table appears), so this is where a spurious DROP
    for such a table is suppressed. All other names pass through unchanged.
    """
    if type_ == "table" and name and name.startswith(_BACKUP_TABLE_PREFIX):
        return False
    return True


def _include_object(object, name, type_, reflected, compare_to):
    """Keep autogenerate clean for migration-owned, ORM-inexpressible objects.

    The users.id -> auth.users(id) FK (added in revision 0002) lives only in the
    Alembic migration: it cannot be expressed in the cross-dialect ORM because
    auth.users is a Supabase/Postgres-only table that is not (and should not be) a
    mapped model -- modeling it would break create_all() under the SQLite dev/test
    mode. Without this exclusion, `alembic revision --autogenerate` would reflect
    the live FK, find no counterpart in the ORM metadata, and propose dropping it.
    The migration is the schema authority for this constraint, so we skip it here.

    Also skips any backup_* table (operator-owned, ORM-inexpressible) as a
    belt-and-suspenders companion to _include_name.
    """
    if type_ == "table" and name and name.startswith(_BACKUP_TABLE_PREFIX):
        return False
    if type_ == "foreign_key_constraint":
        if name == "users_id_fkey":
            return False
        for element in getattr(object, "elements", []):
            target = getattr(element, "target_fullname", "") or ""
            if target.startswith("auth."):
                return False
    return True


# Autogenerate comparison settings. compare_type catches column type drift
# (e.g. timestamptz vs timestamp, text vs varchar). compare_server_default is left
# OFF: server-side defaults live in the DB/migrations, not the ORM, and enabling it
# produces noisy false positives for now()/gen_random_uuid()/CURRENT_TIMESTAMP.
_COMPARE = dict(
    compare_type=True,
    compare_server_default=False,
    include_name=_include_name,
    include_object=_include_object,
)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a live connection)."""
    context.configure(
        url=str(engine.url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_COMPARE,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against the application's engine."""
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            **_COMPARE,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
