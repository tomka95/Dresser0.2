from __future__ import annotations

import logging
import os
import uuid
from dotenv import load_dotenv
from sqlalchemy import CHAR, create_engine, text, TypeDecorator
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

load_dotenv()

logger = logging.getLogger(__name__)


class GUID(TypeDecorator):
    """Cross-dialect UUID: PostgreSQL UUID, SQLite CHAR(36)."""
    impl = CHAR(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value
        return str(value) if isinstance(value, uuid.UUID) else value

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(value) if value else None


class DatabaseConfigError(RuntimeError):
    """Raised when the database is misconfigured or unreachable.

    This is intentionally loud: the app must talk to its *configured* database or
    stop. It must never silently degrade to a local/empty database, because that
    masks an outage and lets the app run against the wrong data.
    """


_LOCAL_SQLITE_URL = "sqlite:///./tailor.db"
_LOCAL_POSTGRES_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/tailor?sslmode=disable"

_TRUTHY = {"1", "true", "yes", "on"}


def _make_engine(url: str):
    if url.startswith("sqlite"):
        return create_engine(url, echo=False, connect_args={"check_same_thread": False})
    return create_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )


def _redact(url: str) -> str:
    """Strip credentials from a SQLAlchemy URL for safe logging/error messages."""
    try:
        return make_url(url).render_as_string(hide_password=True)
    except Exception:
        # Never let logging/error formatting leak a raw URL with a password.
        return url.split("@")[-1] if "@" in url else url


def _local_mode() -> str | None:
    """Return the explicitly requested local-dev backend, or None.

    Developers opt in deliberately with LOCAL_DB=sqlite|postgres (or the
    convenience alias USE_SQLITE=1). There is no automatic/implicit local mode:
    without one of these flags an unreachable configured DB is a hard failure.
    """
    raw = (os.getenv("LOCAL_DB") or "").strip().lower()
    if raw in ("sqlite", "postgres"):
        return raw
    if raw:
        raise DatabaseConfigError(
            f"LOCAL_DB={raw!r} is not valid. Use LOCAL_DB=sqlite or LOCAL_DB=postgres."
        )
    if (os.getenv("USE_SQLITE") or "").strip().lower() in _TRUTHY:
        return "sqlite"
    return None


def _build_database_url() -> str:
    """Decide which database the app connects to.

    Order of precedence:
      1. Explicit local-dev opt-in (LOCAL_DB / USE_SQLITE) -> local sqlite/postgres.
      2. Configured remote DB (DATABASE_URL/DATABASE_URI, or assembled DB_* vars).
    Missing remote configuration is a hard error -- we do NOT fall back to
    localhost defaults, because that silently hides broken configuration.
    """
    mode = _local_mode()
    if mode == "sqlite":
        logger.warning(
            "LOCAL_DB/USE_SQLITE set: using local SQLite file (tailor.db). "
            "Local dev only -- never use this against production data."
        )
        return _LOCAL_SQLITE_URL
    if mode == "postgres":
        logger.warning(
            "LOCAL_DB=postgres set: using local Postgres at localhost:5432/tailor. "
            "Local dev only."
        )
        return _LOCAL_POSTGRES_URL

    url = (os.getenv("DATABASE_URL") or os.getenv("DATABASE_URI") or "").strip()
    if url:
        return url

    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME")
    missing = [
        key
        for key, value in (
            ("DB_USER", user),
            ("DB_PASSWORD", password),
            ("DB_HOST", host),
            ("DB_NAME", name),
        )
        if not value
    ]
    if missing:
        raise DatabaseConfigError(
            "Database is not configured. Set DATABASE_URL (or all of "
            "DB_USER, DB_PASSWORD, DB_HOST, DB_NAME), or opt into local development "
            "explicitly with LOCAL_DB=sqlite (or LOCAL_DB=postgres). "
            f"Missing required variable(s): {', '.join(missing)}. "
            "Refusing to fall back to a local database silently."
        )
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}?sslmode=require"


DATABASE_URL = _build_database_url()
engine = _make_engine(DATABASE_URL)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


Base = declarative_base()


def check_database_connection() -> None:
    """Verify the configured database is reachable, or fail loudly.

    Called once at application startup. On failure it raises a descriptive
    DatabaseConfigError instead of silently switching to a local database.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as exc:
        raise DatabaseConfigError(
            f"Could not connect to the configured database ({_redact(DATABASE_URL)}). "
            "Verify the database is reachable and the credentials are correct. "
            "To develop without the real database, set LOCAL_DB=sqlite (or LOCAL_DB=postgres). "
            "The app will not silently fall back to a local database.\n"
            f"Underlying error: {exc}"
        ) from exc



