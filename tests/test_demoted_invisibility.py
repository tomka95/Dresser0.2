"""Demoted rows ('rejected_recommendation', 0040) must be invisible EVERYWHERE
the user or the pipelines look: review deck, settle accounting, image-fill /
generation selection, and the confirm chokepoint. needs_enrichment rows must be
admitted-but-generation-excluded WITHOUT holding the batch banner hostage.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, engine
from app.gmail_closet.review_service import (
    ConfirmError,
    confirm_candidates,
    list_pending_candidates,
    settle_counts,
)
from app.models import IngestCandidate, IngestRun, User
from app.services.readiness import TERMINAL_STATES, advance


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
    u = User(email=f"demo-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


def _cand(db, user, sync_id, *, state="staged", needs_enrichment=False,
          reason=None, name="Define Jacket"):
    c = IngestCandidate(
        user_id=user.id, sync_id=sync_id, name=name, category="outerwear",
        source_line_key=uuid.uuid4().hex, status="pending", source_type="gmail",
        pipeline_state=state, person_status="unknown",
        needs_enrichment=needs_enrichment, quarantine_reason=reason,
    )
    db.add(c); db.commit(); db.refresh(c)
    return c


def test_demoted_is_terminal_and_never_advances():
    assert "rejected_recommendation" in TERMINAL_STATES

    class _C:
        pipeline_state = "rejected_recommendation"

    c = _C()
    advance(c, "image_pending")
    assert c.pipeline_state == "rejected_recommendation"   # terminal: never revived by advance


def test_demoted_rows_invisible_in_deck(db, user):
    sync = uuid.uuid4()
    _cand(db, user, sync, state="rejected_recommendation", reason="recommendation_tile")
    ready = _cand(db, user, sync, state="ready", name="Real Jacket")

    views = list_pending_candidates(db, user.id, sync_id=sync)
    names = {v["name"] for v in views}
    assert names == {"Real Jacket"}


def test_demoted_rows_do_not_block_settle(db, user):
    sync = uuid.uuid4()
    _cand(db, user, sync, state="ready")
    _cand(db, user, sync, state="rejected_recommendation", reason="marketing_email")

    counts = settle_counts(db, user.id, str(sync))
    assert counts.settled is True          # the demoted row is out of the accounting
    assert counts.ready == 1 and counts.unsettled == 0


def test_needs_enrichment_rows_do_not_block_settle(db, user):
    sync = uuid.uuid4()
    _cand(db, user, sync, state="ready")
    _cand(db, user, sync, state="staged", needs_enrichment=True, name="Black-L")

    counts = settle_counts(db, user.id, str(sync))
    assert counts.settled is True          # excluded-from-generation row can't hold the banner
    assert counts.ready == 1


def test_demoted_row_cannot_be_confirmed(db, user):
    sync = uuid.uuid4()
    db.add(IngestRun(sync_id=sync, user_id=user.id, status="completed")); db.commit()
    demoted = _cand(db, user, sync, state="rejected_recommendation", reason="marketing_email")

    with pytest.raises(ConfirmError):
        confirm_candidates(db, user.id, accepted=[str(demoted.id)], rejected=[])
