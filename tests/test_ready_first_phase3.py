"""Ready-first Phase 3 (final): whole-batch settle for the Home review banner.

The contract this file locks down (G3, end-to-end):
  * The banner fires for a sync ONLY when EVERY pending candidate in it is TERMINAL
    ('ready' or 'failed') AND at least one is 'ready'. ANY mid-pipeline state
    (staged / canonicalized / image_pending / image_generated / verified_clean)
    withholds it.
  * An all-'failed' batch is SILENT — indistinguishable from an empty inbox.
  * The deck serves ONLY 'ready' (failed/pending/raw never appear; failed are counted
    in logs, no user-facing error).
  * Show-once + server-driven: surfaced/dismissed state lives on the run row.
  * Race-freedom: a committed 'ready' row is always a fully-written row (the invariant
    is validated in the same transaction that writes the state).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, engine
from app.gmail_closet.image_fill_service import mark_candidate_ready
from app.gmail_closet.review_service import list_pending_candidates
from app.models import IngestCandidate, IngestRun, User
from tests._authutil import mint_supabase_token
from main import app

# Every NON-terminal state must individually withhold the banner.
_IN_FLIGHT = ["staged", "canonicalized", "image_pending", "image_generated", "verified_clean"]


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
    u = User(email=f"p3-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


def _auth(user):
    return {"Authorization": f"Bearer {mint_supabase_token(sub=str(user.id))}"}


def _run(db, user, *, status="completed"):
    r = IngestRun(
        sync_id=uuid.uuid4(), user_id=user.id, status=status,
        finished_at=datetime.now(timezone.utc),
    )
    db.add(r); db.commit(); db.refresh(r)
    return r


def _cand(db, user, sync_id, *, state="ready", person="person_free",
          image="https://cdn/card.jpg", status="pending", size="M"):
    c = IngestCandidate(
        user_id=user.id, sync_id=sync_id, source_line_key=uuid.uuid4().hex,
        name="Define Jacket", category="outerwear", size=size, status=status,
        source_type="gmail", image_url=image,
        image_status=("resolved" if image else "pending"),
        person_status=person, pipeline_state=state,
    )
    db.add(c); db.commit(); db.refresh(c)
    return c


def _banner(client, user):
    return client.get("/gmail/ingest/pending-review", headers=_auth(user)).json()


# ===========================================================================
# 1. Whole-batch settle
# ===========================================================================

@pytest.mark.parametrize("in_flight", _IN_FLIGHT)
def test_banner_withheld_while_any_item_non_terminal(client, db, user, in_flight):
    r = _run(db, user)
    _cand(db, user, str(r.sync_id))                       # ready
    _cand(db, user, str(r.sync_id), state=in_flight,      # one straggler, any stage
          person="unknown", image=None)
    assert _banner(client, user)["pending"] is False


def test_banner_fires_when_all_terminal_and_one_ready(client, db, user):
    r = _run(db, user)
    _cand(db, user, str(r.sync_id))
    _cand(db, user, str(r.sync_id))
    _cand(db, user, str(r.sync_id), state="failed", person="person_present", image=None)
    body = _banner(client, user)
    assert body["pending"] is True
    assert body["sync_id"] == str(r.sync_id)
    assert body["ready_count"] == 2                       # failed excluded from the count


def test_all_failed_batch_is_silent_like_empty_inbox(client, db, user):
    r = _run(db, user)
    for _ in range(3):
        _cand(db, user, str(r.sync_id), state="failed", person="person_present", image=None)
    body = _banner(client, user)
    assert body == {"pending": False, "sync_id": None, "ready_count": 0}


def test_banner_withheld_while_run_still_running(client, db, user):
    # Even a fully-ready batch stays silent until the run itself is finalized.
    r = _run(db, user, status="running")
    _cand(db, user, str(r.sync_id))
    assert _banner(client, user)["pending"] is False


def test_settled_older_run_surfaces_when_newest_still_in_flight(client, db, user):
    # Per-sync settle: an in-flight NEWER batch must not mute an already-settled one.
    newer = _run(db, user)
    _cand(db, user, str(newer.sync_id), state="image_pending", person="unknown", image=None)
    older = _run(db, user)
    _cand(db, user, str(older.sync_id))
    body = _banner(client, user)
    assert body["pending"] is True
    assert body["sync_id"] == str(older.sync_id)


# ===========================================================================
# 2. Deck: only 'ready', failed silently excluded (logged)
# ===========================================================================

def test_deck_returns_only_ready_never_failed_or_in_flight(db, user, caplog):
    import logging
    sync = str(uuid.uuid4())
    ready = _cand(db, user, sync)
    _cand(db, user, sync, state="failed", person="person_present", image=None)
    for st in _IN_FLIGHT:
        _cand(db, user, sync, state=st, person="unknown", image=None)

    with caplog.at_level(logging.INFO, logger="app.gmail_closet.review_service"):
        rows = list_pending_candidates(db, user.id, sync_id=sync)

    assert [row["candidate_id"] for row in rows] == [str(ready.id)]
    # failed candidates: no user-facing error, but an ops-visible count in the log.
    assert any("terminally-failed" in rec.message for rec in caplog.records)


def test_deck_card_is_complete_and_person_free(db, user):
    # What the deck serves is exactly the Gate-3 card: tags + a clean displayable image.
    sync = str(uuid.uuid4())
    _cand(db, user, sync)
    (row,) = list_pending_candidates(db, user.id, sync_id=sync)
    assert row["image_url"] == "https://cdn/card.jpg"     # person_free -> displayable
    assert row["person_status"] == "person_free"
    assert row["pipeline_state"] == "ready"
    assert row["name"] and row["category"] and row["size"]


# ===========================================================================
# 3. Show-once + server-driven
# ===========================================================================

def _settled_run(client, db, user):
    r = _run(db, user)
    _cand(db, user, str(r.sync_id))
    assert _banner(client, user)["pending"] is True
    return r


def test_show_once_after_open(client, db, user):
    r = _settled_run(client, db, user)
    resp = client.post(
        "/gmail/ingest/pending-review/ack",
        json={"sync_id": str(r.sync_id), "action": "opened"},
        headers=_auth(user),
    )
    assert resp.status_code == 204
    assert _banner(client, user)["pending"] is False      # never re-nags


def test_show_once_after_dismiss(client, db, user):
    r = _settled_run(client, db, user)
    client.post(
        "/gmail/ingest/pending-review/ack",
        json={"sync_id": str(r.sync_id), "action": "dismissed"},
        headers=_auth(user),
    )
    assert _banner(client, user)["pending"] is False


def test_server_driven_state_survives_new_client(client, db, user):
    # State lives on the run row, not the device: a "new device" (fresh client) sees the
    # same surfaced state after an ack from the old one.
    r = _settled_run(client, db, user)
    client.post(
        "/gmail/ingest/pending-review/ack",
        json={"sync_id": str(r.sync_id), "action": "opened"},
        headers=_auth(user),
    )
    fresh_client = TestClient(app)
    assert _banner(fresh_client, user)["pending"] is False


def test_ack_rejects_foreign_sync(client, db, user):
    other = User(email=f"p3x-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    db.add(other); db.commit(); db.refresh(other)
    r = _run(db, other)
    resp = client.post(
        "/gmail/ingest/pending-review/ack",
        json={"sync_id": str(r.sync_id), "action": "opened"},
        headers=_auth(user),
    )
    assert resp.status_code == 404                        # cross-user reject


# ===========================================================================
# 4. Race-freedom: no surfacing on a partially-written row
# ===========================================================================

def test_ready_cannot_be_written_on_incomplete_row(db, user):
    # The ONLY writer of 'ready' validates the full readiness invariant on the same row
    # in the same transaction — a partially-written candidate cannot become 'ready', so
    # the settle condition can never count one.
    sync = str(uuid.uuid4())
    incomplete = _cand(db, user, sync, state="verified_clean", person="person_free",
                       image=None)                        # image not yet stored
    with pytest.raises(AssertionError):
        mark_candidate_ready(incomplete)
    assert incomplete.pipeline_state == "verified_clean"  # unchanged -> banner withheld


def test_settle_counts_only_committed_ready(client, db, user):
    # A candidate that has its image + person verdict but has NOT been stamped 'ready'
    # (e.g. crash between the field writes and the stamp pass) withholds the banner —
    # the settle condition reads pipeline_state, never infers readiness from fields.
    r = _run(db, user)
    _cand(db, user, str(r.sync_id))                       # ready
    _cand(db, user, str(r.sync_id), state="verified_clean")  # fields fine, not stamped
    assert _banner(client, user)["pending"] is False
