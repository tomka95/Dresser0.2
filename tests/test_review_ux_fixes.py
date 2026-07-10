"""Two UX fixes (2026-07-10): size is optional, and failed items are visible in review.

Fix 1 — size never gates 'ready' for ANY category.
Fix 2 — a terminal 'failed' candidate surfaces (reason + retry/dismiss, never a person
image) and the retry/dismiss endpoints work.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, engine
from app.gmail_closet.review_service import (
    dismiss_candidate,
    list_pending_candidates,
    retry_candidate,
)
from app.models import IngestCandidate, User
from app.services import readiness
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
def user(db: Session):
    u = User(email="ux@example.com", hashed_password="x", display_name="U")
    db.add(u); db.commit(); db.refresh(u)
    return u


def _auth(user):
    return {"Authorization": f"Bearer {mint_supabase_token(sub=str(user.id))}"}


def _photo_cand(db, user, **over):
    fields = dict(
        user_id=user.id, sync_id=uuid4(), source_type="photo", status="pending",
        source_line_key=f"k-{uuid4().hex[:8]}",
        image_url="https://blob/cut.jpg", image_status="user_uploaded",
        name="Camel Coat", category="outerwear", color="camel", size=None,
        pipeline_state="verified_clean", person_status="person_free",
        generation_status="ready", generated_image_url="https://cdn/card.png",
    )
    fields.update(over)
    c = IngestCandidate(**fields)
    db.add(c); db.commit(); db.refresh(c)
    return c


# ===========================================================================
# FIX 1 — size optional for EVERY category
# ===========================================================================

@pytest.mark.parametrize("category", ["top", "bottom", "dress", "outerwear", "footwear"])
def test_sized_category_reaches_ready_without_size(db, user, category):
    c = _photo_cand(db, user, category=category, size=None)
    # tags_ready no longer needs size; mark_candidate_ready succeeds.
    assert readiness.tags_ready(c) is True
    readiness.mark_candidate_ready(c)
    assert c.pipeline_state == "ready"
    # The soft 'add size' affordance is still offered (never required).
    assert readiness.needs_size(c) is True


def test_needs_size_is_soft_flag_not_a_gate(db, user):
    ready_card = _photo_cand(db, user, category="top", size=None, pipeline_state="ready")
    # A fully-ready card with no size STILL offers the affordance — it never blocked it.
    assert readiness.needs_size(ready_card) is True
    sized = _photo_cand(db, user, category="top", size="M", pipeline_state="ready")
    assert readiness.needs_size(sized) is False


# ===========================================================================
# FIX 2 — failed items visible, with retry/dismiss, never a person image
# ===========================================================================

def test_failed_candidate_surfaces_with_reason_no_image(db, user):
    _photo_cand(db, user, pipeline_state="ready", generation_status="ready")  # a normal card
    failed = _photo_cand(
        db, user, pipeline_state="failed", generation_status="failed",
        person_status="person_present", generated_image_url=None,
        image_url="https://blob/person-crop.jpg", source_line_key="z-failed",
    )
    rows = list_pending_candidates(db, user.id)
    fe = next(r for r in rows if r["candidate_id"] == str(failed.id))
    assert fe["review_state"] == "failed"
    assert "person" in fe["failure_reason"].lower()          # honest, person-aware reason
    assert fe["image_url"] is None and fe["generated_image_url"] is None
    # The person crop URL appears NOWHERE in the payload (invariant holds).
    assert "person-crop" not in str(fe)


def test_retry_endpoint_requeues_failed_candidate(db, user, monkeypatch):
    import app.photo_closet.generation_service as gen
    monkeypatch.setattr(gen, "self_heal_background", lambda uid: None)
    failed = _photo_cand(
        db, user, pipeline_state="failed", generation_status="failed",
        generation_attempts=3, generated_image_url=None, source_line_key="z-retry",
    )
    client = TestClient(app)
    resp = client.post(
        f"/gmail/ingest/candidates/{failed.id}/retry", headers=_auth(user))
    assert resp.status_code == 200 and resp.json()["ok"] is True
    db.refresh(failed)
    assert failed.pipeline_state == "image_pending"
    assert failed.generation_status == "pending_retry"
    assert failed.generation_attempts == 0                   # ledger reset


def test_retry_rejects_non_failed_and_foreign(db, user, monkeypatch):
    import app.photo_closet.generation_service as gen
    monkeypatch.setattr(gen, "self_heal_background", lambda uid: None)
    ready = _photo_cand(db, user, pipeline_state="ready")
    client = TestClient(app)
    # not failed -> 404
    assert client.post(
        f"/gmail/ingest/candidates/{ready.id}/retry", headers=_auth(user)
    ).status_code == 404
    # unknown id -> 404
    assert client.post(
        f"/gmail/ingest/candidates/{uuid4()}/retry", headers=_auth(user)
    ).status_code == 404
    # service-level: not owned by the user
    other = User(email="other@example.com", hashed_password="x", display_name="O")
    db.add(other); db.commit(); db.refresh(other)
    assert retry_candidate(db, other.id, str(ready.id)) is False


def test_dismiss_endpoint_removes_from_deck(db, user):
    failed = _photo_cand(
        db, user, pipeline_state="failed", generation_status="failed",
        generated_image_url=None, source_line_key="z-dismiss",
    )
    client = TestClient(app)
    resp = client.post(
        f"/gmail/ingest/candidates/{failed.id}/dismiss", headers=_auth(user))
    assert resp.status_code == 200 and resp.json()["ok"] is True
    db.refresh(failed)
    assert failed.status == "rejected"                       # left the pending deck
    assert list_pending_candidates(db, user.id) == []


def test_dismiss_foreign_is_noop(db, user):
    failed = _photo_cand(db, user, pipeline_state="failed", generated_image_url=None)
    other = User(email="other2@example.com", hashed_password="x", display_name="O2")
    db.add(other); db.commit(); db.refresh(other)
    assert dismiss_candidate(db, other.id, str(failed.id)) is False
    db.refresh(failed)
    assert failed.status == "pending"                        # untouched
