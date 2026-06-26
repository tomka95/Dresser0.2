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
