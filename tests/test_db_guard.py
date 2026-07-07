"""Tests for the engine-layer guard that blocks the test suite from touching a
remote (Supabase/production) database.

The closet fixtures call Base.metadata.create_all()/drop_all() on the shared
engine; this guard makes it structurally impossible for that engine to point at a
non-local host while running under pytest, unless ALLOW_REMOTE_TEST_DB=1 is set.
"""

import pytest

from app.core.config import settings
from app.db import _make_engine, DatabaseConfigError

REMOTE = "postgresql+psycopg2://u:p@db.example.supabase.co:5432/postgres?sslmode=require"
LOCAL_PG = "postgresql+psycopg2://postgres:postgres@localhost:5432/tailor?sslmode=disable"
LOCAL_PG_IP = "postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/tailor"
SQLITE = "sqlite:///./_guard_test.db"


def test_remote_host_is_blocked_under_pytest():
    with pytest.raises(DatabaseConfigError):
        _make_engine(REMOTE)


def test_localhost_postgres_is_allowed():
    _make_engine(LOCAL_PG)  # must not raise
    _make_engine(LOCAL_PG_IP)


def test_sqlite_is_allowed():
    _make_engine(SQLITE)  # must not raise


def test_explicit_override_allows_remote(monkeypatch):
    # ALLOW_REMOTE_TEST_DB now flows through the `settings` singleton (P3.1), which
    # is built once at import time -- monkeypatch.setenv() alone would arrive too
    # late. Patch the resolved setting directly, same pattern as the Supabase-auth
    # fixtures in conftest.py.
    monkeypatch.setattr(settings, "ALLOW_REMOTE_TEST_DB", "1")
    _make_engine(REMOTE)  # must not raise when explicitly overridden
