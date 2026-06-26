import logging
import os
import uuid
from dotenv import load_dotenv
from sqlalchemy import CHAR, create_engine, text, TypeDecorator
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


def _local_postgres_url():
    return "postgresql+psycopg2://postgres:postgres@localhost:5432/tailor?sslmode=disable"


def _sqlite_url():
    return "sqlite:///./tailor.db"


def _make_engine(url: str):
    if url.startswith("sqlite"):
        return create_engine(url, echo=False, connect_args={"check_same_thread": False})
    return create_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )


DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URI")

if not DATABASE_URL or not DATABASE_URL.strip():
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME", "tailor")
    use_ssl = DB_HOST not in ("localhost", "127.0.0.1")
    ssl_param = "sslmode=require" if use_ssl else "sslmode=disable"
    DATABASE_URL = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?{ssl_param}"

engine = _make_engine(DATABASE_URL)

# Fallback chain: configured DB -> local Postgres -> SQLite (no server required)
for attempt, (label, fallback_url) in enumerate([
    ("configured", None),
    ("local Postgres", _local_postgres_url()),
    ("SQLite file", _sqlite_url()),
]):
    try:
        if fallback_url is not None:
            if attempt == 1:
                logger.warning("Configured database unreachable. Trying local Postgres.")
            elif attempt == 2:
                logger.warning("Local Postgres unreachable. Using SQLite file (tailor.db).")
            DATABASE_URL = fallback_url
            engine = _make_engine(DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        break
    except OperationalError as e:
        err_str = str(e).lower()
        unreachable = "could not translate host name" in err_str or "connection refused" in err_str or "connection" in err_str
        if fallback_url is None and unreachable:
            continue
        if fallback_url is None:
            raise
        if fallback_url == _local_postgres_url() and unreachable:
            continue
        if fallback_url == _local_postgres_url():
            raise
        if fallback_url == _sqlite_url():
            raise
        continue

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


Base = declarative_base()



