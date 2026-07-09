"""Wave C / Fix 1: onboarding auto-scan dispatch + the Home pending-review banner.

Covers: the onboarding connect auto-starts a background scan (stamped trigger='onboarding')
and is 409-idempotent when a run is already live; GET /gmail/ingest/pending-review surfaces
a completed run ONLY once its image phase has settled and only while it has pending
candidates the user hasn't opened/dismissed (empty inbox -> silent; show-once).
"""
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.api.routes.gmail_ingest as gi
from app.api.routes.gmail_ingest import maybe_start_onboarding_scan
from app.core.config import settings
from app.db import Base, SessionLocal, engine
from app.models import GoogleAccount, IngestCandidate, IngestRun, User
from tests._authutil import mint_supabase_token
from main import app


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
def client():
    return TestClient(app)


@pytest.fixture
def user(db: Session):
    u = User(email=f"onb-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


def _auth(user):
    return {"Authorization": f"Bearer {mint_supabase_token(sub=str(user.id))}"}


def _connected_account(db, user):
    # Explicit id: SQLite doesn't autoincrement a BigInteger PK (Postgres does in prod).
    db.add(GoogleAccount(id=1, user_id=user.id, access_token="enc-acc", refresh_token="enc-ref", scope="s"))
    db.commit()


def _run(db, user, **over):
    r = IngestRun(
        sync_id=uuid.uuid4(),
        user_id=user.id,
        status=over.pop("status", "completed"),
        trigger=over.pop("trigger", "onboarding"),
        generation_total=over.pop("generation_total", 0),
        generation_ready=over.pop("generation_ready", 0),
        generation_failed=over.pop("generation_failed", 0),
        finished_at=over.pop("finished_at", datetime.now(timezone.utc)),
        **over,
    )
    db.add(r); db.commit(); db.refresh(r)
    return r


def _cand(db, user, run, *, status="pending", key=None):
    c = IngestCandidate(
        user_id=user.id, sync_id=run.sync_id, status=status,
        name="Blue Tee", source_line_key=key or uuid.uuid4().hex,
    )
    db.add(c); db.commit()
    return c


# --------------------------------------------------------------------------- auto-scan
def test_auto_scan_starts_new_run_with_onboarding_trigger(db, user, monkeypatch):
    monkeypatch.setattr(settings, "JOBS_GMAIL_INGEST_ENABLED", False)
    monkeypatch.setattr(gi, "ingest_background", lambda uid, sid: None)
    _connected_account(db, user)

    bt = BackgroundTasks()
    sync_id = maybe_start_onboarding_scan(db, user.id, bt)

    assert sync_id is not None
    run = db.query(IngestRun).filter(IngestRun.user_id == user.id).one()
    assert run.status == "running" and run.trigger == "onboarding"
    assert len(bt.tasks) == 1  # BackgroundTask dispatched (flag OFF path)


def test_auto_scan_idempotent_when_a_run_is_already_live(db, user, monkeypatch):
    monkeypatch.setattr(settings, "JOBS_GMAIL_INGEST_ENABLED", False)
    monkeypatch.setattr(gi, "ingest_background", lambda uid, sid: None)
    _connected_account(db, user)
    live = _run(db, user, status="running", finished_at=None)

    bt = BackgroundTasks()
    sync_id = maybe_start_onboarding_scan(db, user.id, bt)

    assert sync_id == str(live.sync_id)          # reused the live run
    assert db.query(IngestRun).filter(IngestRun.user_id == user.id).count() == 1  # no double-start
    assert len(bt.tasks) == 0


def test_auto_scan_noop_without_connection(db, user):
    # No stored refresh token -> nothing to scan.
    assert maybe_start_onboarding_scan(db, user.id, BackgroundTasks()) is None


# --------------------------------------------------------------------------- pending-review
def test_pending_review_surfaces_completed_run_with_candidates(client, db, user):
    run = _run(db, user)                 # completed, generation_total=0 -> settled
    _cand(db, user, run)
    _cand(db, user, run)
    r = client.get("/gmail/ingest/pending-review", headers=_auth(user))
    assert r.status_code == 200
    body = r.json()
    assert body["pending"] is True
    assert body["sync_id"] == str(run.sync_id)
    assert body["ready_count"] == 2


def test_pending_review_silent_when_empty_inbox(client, db, user):
    _run(db, user)                       # completed run, but zero pending candidates
    r = client.get("/gmail/ingest/pending-review", headers=_auth(user))
    assert r.json() == {"pending": False, "sync_id": None, "ready_count": 0}


def test_pending_review_silent_when_generation_not_settled(client, db, user):
    # generation still in flight (ready+failed < total) -> don't surface half-imaged cards.
    run = _run(db, user, generation_total=3, generation_ready=1, generation_failed=0)
    _cand(db, user, run)
    assert client.get("/gmail/ingest/pending-review", headers=_auth(user)).json()["pending"] is False


def test_pending_review_surfaces_once_generation_settled(client, db, user):
    run = _run(db, user, generation_total=2, generation_ready=1, generation_failed=1)
    _cand(db, user, run)
    assert client.get("/gmail/ingest/pending-review", headers=_auth(user)).json()["pending"] is True


def test_pending_review_silent_for_running_run(client, db, user):
    run = _run(db, user, status="running", finished_at=None)
    _cand(db, user, run)
    assert client.get("/gmail/ingest/pending-review", headers=_auth(user)).json()["pending"] is False


def test_pending_review_show_once_after_open(client, db, user):
    run = _run(db, user)
    _cand(db, user, run)
    assert client.get("/gmail/ingest/pending-review", headers=_auth(user)).json()["pending"] is True

    ack = client.post(
        "/gmail/ingest/pending-review/ack",
        json={"sync_id": str(run.sync_id), "action": "opened"},
        headers=_auth(user),
    )
    assert ack.status_code == 204
    # ...never reappears for that run.
    assert client.get("/gmail/ingest/pending-review", headers=_auth(user)).json()["pending"] is False


def test_pending_review_show_once_after_dismiss(client, db, user):
    run = _run(db, user)
    _cand(db, user, run)
    client.post(
        "/gmail/ingest/pending-review/ack",
        json={"sync_id": str(run.sync_id), "action": "dismissed"},
        headers=_auth(user),
    )
    assert client.get("/gmail/ingest/pending-review", headers=_auth(user)).json()["pending"] is False


def test_pending_review_requires_auth(client):
    assert client.get("/gmail/ingest/pending-review").status_code == 401


def test_ack_foreign_run_is_404(client, db, user):
    other = User(email=f"other-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    db.add(other); db.commit(); db.refresh(other)
    run = _run(db, other)
    r = client.post(
        "/gmail/ingest/pending-review/ack",
        json={"sync_id": str(run.sync_id), "action": "opened"},
        headers=_auth(user),
    )
    assert r.status_code == 404
