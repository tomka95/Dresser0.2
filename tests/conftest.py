"""Pytest configuration for the Tailor backend test suite.

Tests run against a throwaway SQLite database. We set the explicit LOCAL_DB
opt-in BEFORE app modules import `app.db`, because `app.db` now resolves its
connection at import time and will fail loudly if no database is configured.

This mirrors the intended developer workflow: local/ephemeral databases are an
explicit, deliberate choice -- never a silent fallback.
"""

import os

# Must be set before any `from app.db import ...` / `from main import app`.
os.environ.setdefault("LOCAL_DB", "sqlite")

import pytest

from tests._authutil import (
    PUBLIC_JWK,
    TEST_ISSUER_BASE,
    mint_supabase_token,
)


@pytest.fixture(autouse=True)
def _supabase_auth_env(monkeypatch):
    """Enable Supabase Auth (the only accepted identity path) for every test.

    Points the verifier at a test issuer and stubs the JWKS fetch with the
    throwaway public key from tests/_authutil, so tokens minted by
    `mint_supabase_token` verify without any network. Individual tests can
    monkeypatch these back off to exercise the fail-closed / unconfigured path.
    """
    import app.supabase_auth as sa
    from app.core.config import settings

    monkeypatch.setattr(settings, "SUPABASE_URL", TEST_ISSUER_BASE)
    monkeypatch.setattr(settings, "SUPABASE_PROJECT_REF", None)
    monkeypatch.setattr(settings, "SUPABASE_JWKS_URL", None)
    monkeypatch.setattr(settings, "SUPABASE_JWT_ISSUER", None)
    monkeypatch.setattr(sa, "_fetch_jwks", lambda: [PUBLIC_JWK])
    sa._reset_cache_for_tests()
    yield
    sa._reset_cache_for_tests()


@pytest.fixture(scope="session")
def mint_token():
    """Convenience fixture returning the Supabase-token minting function."""
    return mint_supabase_token
