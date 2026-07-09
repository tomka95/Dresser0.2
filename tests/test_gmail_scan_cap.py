"""DEV-ONLY Gmail scan cap (#5): a pure bound on the receipt scan that is STRUCTURALLY
incapable of affecting prod. With the flag OFF (the default) the scan is unbounded and
uses the full GMAIL_MAX_YEARS window; only with the flag explicitly ON is the message
count + window bounded. No network — the list/query/token seams are faked.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

import app.gmail_closet.fetch_service as fs
from app.core.config import settings
from app.db import Base, SessionLocal, engine
from app.gmail_closet.gmail_oauth_client import default_since
from app.models import GoogleAccount, IngestRun, User


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def user(db: Session):
    u = User(email=f"scan-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


# --------------------------------------------------------------------------- _list_all_ids
class _PagingClient:
    """Two pages of ids; records how many list calls happened (to prove early-stop)."""

    def __init__(self):
        self.list_calls = 0

    def get(self, url, headers=None, params=None, timeout=None):
        self.list_calls += 1
        page = 1 if "pageToken" not in params else 2
        ids = [f"p{page}-{i}" for i in range(3)]
        body = {"resultSizeEstimate": 6, "messages": [{"id": i} for i in ids]}
        if page == 1:
            body["nextPageToken"] = "PAGE2"

        class _R:
            status_code = 200
            def raise_for_status(self_inner): return None
            def json(self_inner): return body
        return _R()


def test_list_all_ids_unbounded_collects_every_page():
    client = _PagingClient()
    ids, estimate = fs._list_all_ids(client, "tok", "Q", None)  # prod: no cap
    assert len(ids) == 6 and client.list_calls == 2  # walked both pages


def test_list_all_ids_dev_cap_truncates_and_stops_early():
    client = _PagingClient()
    ids, estimate = fs._list_all_ids(client, "tok", "Q", 2)  # dev cap = 2
    assert ids == ["p1-0", "p1-1"]        # truncated to the cap
    assert client.list_calls == 1         # stopped after page 1 — never paged again


# --------------------------------------------------------------------------- window + cap wiring
def _run_core_capturing(db, user, monkeypatch):
    """Drive _run_ingest_core with the list/query/token seams faked; capture the
    `since` window and the `max_messages` cap the scan was configured with."""
    captured = {}

    def _fake_build_query(since):
        captured["since"] = since
        return "Q"

    def _fake_list(http, token, query, max_messages=None):
        captured["max_messages"] = max_messages
        return [], 0

    monkeypatch.setattr(fs, "ensure_fresh_token", lambda acct, db: "tok")
    monkeypatch.setattr(fs, "_build_query", _fake_build_query)
    monkeypatch.setattr(fs, "_list_all_ids", _fake_list)

    account = GoogleAccount(id=1, user_id=user.id, access_token="a", refresh_token="r", scope="s")
    db.add(account)
    sync_id = uuid.uuid4()
    db.add(IngestRun(sync_id=sync_id, user_id=user.id, status="running"))
    db.commit()

    fs._run_ingest_core(user.id, account, sync_id, db, finalize=True)
    return captured


def test_prod_default_is_unbounded_full_window(db, user, monkeypatch):
    # Flag OFF (the default) -> no message cap, full GMAIL_MAX_YEARS window.
    monkeypatch.setattr(settings, "GMAIL_DEV_SCAN_CAP_ENABLED", False)
    captured = _run_core_capturing(db, user, monkeypatch)

    assert captured["max_messages"] is None                       # unbounded scan
    # since ~= default_since() (a ~2-year window), NOT a short dev window.
    assert captured["since"] <= datetime.utcnow() - timedelta(days=300)
    assert abs((captured["since"] - default_since()).total_seconds()) < 5


def test_dev_flag_bounds_count_and_window(db, user, monkeypatch):
    monkeypatch.setattr(settings, "GMAIL_DEV_SCAN_CAP_ENABLED", True)
    monkeypatch.setattr(settings, "GMAIL_DEV_SCAN_MAX_MESSAGES", 20)
    monkeypatch.setattr(settings, "GMAIL_DEV_SCAN_MAX_DAYS", 90)
    captured = _run_core_capturing(db, user, monkeypatch)

    assert captured["max_messages"] == 20                          # bounded count
    # since ~= now - 90d (short dev window), well inside the 2-year prod window.
    assert captured["since"] >= datetime.utcnow() - timedelta(days=91)
    assert captured["since"] <= datetime.utcnow() - timedelta(days=89)
