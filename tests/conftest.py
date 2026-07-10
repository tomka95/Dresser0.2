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


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live_keys: opt this test in to the REAL provider keys from the local .env "
        "(billable calls possible). Without this marker every test runs with fake keys.",
    )


@pytest.fixture(autouse=True)
def _no_live_keys(request, monkeypatch):
    """KEY-GUARD: no test may make live billable provider calls (Photo-seam Phase 2).

    The local .env carries REAL GEMINI/BFL/Supabase keys and pydantic-settings reads
    it, so without this guard any test that reaches a provider/verify/storage seam
    (e.g. via TestClient's synchronous BackgroundTasks) silently makes LIVE calls —
    billable and nondeterministic (a live verify verdict once flipped an e2e
    assertion).

    Every settings key that could authorize a paid or externally-mutating call is
    replaced with a FAKE value that is still TRUTHY — arming logic (generation_armed,
    provider availability) behaves exactly as in a configured environment, while any
    accidental live call fails authentication instead of billing. Generation/verify/
    storage remain mocked at their seams by the individual suites; this fixture is the
    backstop for the ones that forget.

    A test that genuinely needs live keys opts in with @pytest.mark.live_keys.
    """
    if request.node.get_closest_marker("live_keys"):
        yield
        return
    from app.core.config import settings

    for field in (
        "GEMINI_API_KEY",
        "BFL_API_KEY",
        "FAL_API_KEY",
        "OPENAI_API_KEY",
        "SERPER_API_KEY",
        "SUPABASE_S3_ACCESS_KEY",
        "SUPABASE_S3_SECRET_KEY",
    ):
        monkeypatch.setattr(settings, field, "test-key-not-real", raising=False)
    yield


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
