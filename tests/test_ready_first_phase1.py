"""Ready-first Phase 1: authoritative pipeline_state machine + fail-closed person_status.

Contract under test (G3 foundation):
  * pipeline_state is the ONLY readiness truth; deck + banner gate STRICTLY on 'ready'.
  * person_status is FAIL-CLOSED: 'unknown' (detector never ran) masks identically to
    'person_present'. A raw image is shown ONLY on affirmative 'person_free' (or a
    verified 'ready' generated card). Email candidates are masked exactly like photo.
  * Transitions are server-written: staging -> 'staged'; generation start ->
    'image_pending'; verified card -> 'ready' + 'person_free'; terminal miss -> 'failed'.
Intermediate state (intended): Gmail candidates never reach 'ready' in Phase 1, so the
Gmail deck/banner surface NOTHING until the generation phase (Phase 2) wires them.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

import app.gmail_closet.extraction_service as ES
from app.db import Base, SessionLocal, engine
from app.gmail_closet.extraction_schema import ClosetCategory, ExtractedItem, ExtractedReceipt
from app.gmail_closet.extractor import ExtractionOutcome
from app.gmail_closet.review_service import _candidate_to_view, list_pending_candidates
from app.models import IngestCandidate, IngestRun, User
from app.models.closet import ClothingItem, display_image_url
from app.photo_closet.generation_service import _hold


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
    u = User(email=f"rf-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


def _cand(db, user, sync_id, *, state="staged", person="unknown", src="gmail",
          status="pending", image="https://cdn/img.jpg", gen_status=None, gen_url=None):
    c = IngestCandidate(
        user_id=user.id, sync_id=sync_id, name="Define Jacket", category="outerwear",
        source_line_key=uuid.uuid4().hex, status=status, source_type=src,
        image_url=image, pipeline_state=state, person_status=person,
        generation_status=gen_status, generated_image_url=gen_url,
    )
    db.add(c); db.commit(); db.refresh(c)
    return c


# ===========================================================================
# Staging transitions — entry state written server-side
# ===========================================================================

def test_gmail_staging_writes_staged_and_unknown(monkeypatch):
    captured = []
    monkeypatch.setattr(ES, "_upsert_candidate", lambda db, vals: captured.append(vals))
    receipt = ExtractedReceipt(
        is_purchase=True, is_clothing=True, overall_confidence=0.9,
        items=[ExtractedItem(name="Define Jacket", category=ClosetCategory.outerwear)],
    )
    outcome = ExtractionOutcome(
        receipt=receipt, model="m", escalated=False, parse_failed=False, api_failed=False,
        input_tokens=0, output_tokens=0, est_cost_flash_lite=0.0, est_cost_realistic=0.0,
    )
    res = ES._MsgExtraction(message_id="m1", outcome=outcome, sent_at=None)
    keys = ES._stage_message(None, user_id=uuid.uuid4(), sync_id=uuid.uuid4(), res=res)
    assert len(keys) == 1
    assert captured[0]["pipeline_state"] == "staged"
    assert captured[0]["person_status"] == "unknown"   # fail-closed: no detector ran


def test_photo_staging_writes_affirmative_person_status(db, user):
    from app.photo_closet.ingest_service import _stage_candidate

    class _Conf:
        name = brand = category = color = 0.9

    class _G:
        name = "Crew Tee"
        brand = None
        color = "white"
        confidence_overall = 0.9
        confidence = _Conf()

        class category:
            value = "top"

    on = _stage_candidate(db, user.id, uuid.uuid4(), _G(), "u1", "k-on", on_model=True)
    off = _stage_candidate(db, user.id, uuid.uuid4(), _G(), "u2", "k-off", on_model=False)
    db.commit()
    assert on.pipeline_state == "staged" and on.person_status == "person_present"
    assert off.pipeline_state == "staged" and off.person_status == "person_free"


# ===========================================================================
# Generation transitions — ready / failed written with the card
# ===========================================================================

def test_hold_terminal_goes_failed_else_image_pending(db, user, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "GENERATION_MAX_ATTEMPTS", 2)
    sync = uuid.uuid4()
    db.add(IngestRun(sync_id=sync, user_id=user.id, status="running")); db.commit()

    c = _cand(db, user, sync, src="photo", person="person_present")
    _hold(db, c, sync, count_attempt=True)      # attempt 1 -> retryable
    assert c.pipeline_state == "image_pending"
    _hold(db, c, sync, count_attempt=True)      # attempt 2 -> ceiling -> terminal
    assert c.generation_status == "failed"
    assert c.pipeline_state == "failed"


def test_restage_preserves_ready_candidate(db, user):
    from app.photo_closet.ingest_service import _stage_candidate

    class _Conf:
        name = brand = category = color = 0.9

    class _G:
        name = "Crew Tee"
        brand = None
        color = "white"
        confidence_overall = 0.9
        confidence = _Conf()

        class category:
            value = "top"

    first = _stage_candidate(db, user.id, uuid.uuid4(), _G(), "u", "k-same", on_model=True)
    db.commit()
    first.generation_status = "ready"
    first.generated_image_url = "https://cdn/card.jpg"
    first.pipeline_state = "ready"
    db.commit()
    again = _stage_candidate(db, user.id, uuid.uuid4(), _G(), "u", "k-same", on_model=True)
    db.commit()
    assert again.id == first.id
    assert again.pipeline_state == "ready"      # never regressed to invisible-forever


# ===========================================================================
# Deck — STRICT ready gate
# ===========================================================================

def test_deck_serves_ready_and_failed_not_in_flight(db, user):
    sync = str(uuid.uuid4())
    _cand(db, user, sync, state="staged")
    _cand(db, user, sync, state="image_pending", src="photo", person="person_present")
    failed = _cand(db, user, sync, state="failed", src="photo", person="person_present")
    ready = _cand(db, user, sync, state="ready", person="person_free",
                  gen_status="ready", gen_url="https://cdn/card.jpg")

    rows = list_pending_candidates(db, user.id)
    # Fix 2: ready card + failed entry surface; staged/in-flight do not.
    assert {r["candidate_id"] for r in rows} == {str(ready.id), str(failed.id)}
    fe = next(r for r in rows if r["candidate_id"] == str(failed.id))
    assert fe["review_state"] == "failed" and fe["image_url"] is None


def test_deck_empty_while_gmail_batch_in_flight(db, user):
    # The intended Phase-1 intermediate state: staged Gmail candidates surface NOTHING.
    sync = str(uuid.uuid4())
    for _ in range(3):
        _cand(db, user, sync, state="staged")
    assert list_pending_candidates(db, user.id) == []


# ===========================================================================
# Fail-closed person mask — email identical to photo
# ===========================================================================

def test_view_masks_unknown_person_status_email(db, user):
    c = _cand(db, user, str(uuid.uuid4()), state="ready", person="unknown", src="gmail")
    view = _candidate_to_view(c, None)
    assert view["image_url"] is None            # unchecked NEVER reads as clean
    assert view["person_status"] == "unknown"


def test_view_masks_person_present_photo(db, user):
    c = _cand(db, user, str(uuid.uuid4()), state="ready", person="person_present", src="photo")
    assert _candidate_to_view(c, None)["image_url"] is None


def test_view_shows_only_affirmative_person_free(db, user):
    c = _cand(db, user, str(uuid.uuid4()), state="ready", person="person_free", src="gmail")
    assert _candidate_to_view(c, None)["image_url"] == "https://cdn/img.jpg"


def test_view_mask_source_aware(db, user):
    """'unknown' masks everywhere. person_free surfaces image_url only for GMAIL
    (their verified resolved image IS the card); a PHOTO candidate's image_url is a
    raw source crop — Photo-seam Phase 5 never emits it (the card is
    generated_image_url)."""
    for src in ("gmail", "photo"):
        unknown = _cand(db, user, str(uuid.uuid4()), person="unknown", src=src)
        assert _candidate_to_view(unknown, None)["image_url"] is None
    gmail_free = _cand(db, user, str(uuid.uuid4()), person="person_free", src="gmail")
    assert _candidate_to_view(gmail_free, None)["image_url"] == "https://cdn/img.jpg"
    photo_free = _cand(db, user, str(uuid.uuid4()), person="person_free", src="photo")
    assert _candidate_to_view(photo_free, None)["image_url"] is None


# ===========================================================================
# display_image_url — the single item-level mask, fail-closed
# ===========================================================================

def _item(**kw):
    defaults = dict(image_url="https://cdn/img.jpg", person_status="unknown",
                    generation_status=None, on_model=False)
    defaults.update(kw)
    it = ClothingItem(user_id=uuid.uuid4(), name="x", category="top")
    for k, v in defaults.items():
        setattr(it, k, v)
    return it


def test_display_masks_unknown():
    assert display_image_url(_item()) is None                       # fail-closed default


def test_display_masks_person_present_without_card():
    assert display_image_url(_item(person_status="person_present")) is None


def test_display_shows_person_free():
    assert display_image_url(_item(person_status="person_free")) == "https://cdn/img.jpg"


def test_display_shows_verified_ready_card_regardless_of_person_status():
    # A 'ready' image IS the verified person-free card (pair verify hard-fails persons).
    assert display_image_url(
        _item(person_status="person_present", generation_status="ready")
    ) == "https://cdn/img.jpg"


def test_display_email_item_masked_like_photo_item():
    email = _item(person_status="unknown")
    photo = _item(person_status="unknown", on_model=True)
    assert display_image_url(email) is None
    assert display_image_url(photo) is None


# ===========================================================================
# Banner — whole-batch settle on pipeline_state
# ===========================================================================

def _run(db, user, *, status="completed"):
    from datetime import datetime, timezone
    r = IngestRun(
        sync_id=uuid.uuid4(), user_id=user.id, status=status,
        finished_at=datetime.now(timezone.utc),
    )
    db.add(r); db.commit(); db.refresh(r)
    return r


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


def _auth(user):
    from tests._authutil import mint_supabase_token
    return {"Authorization": f"Bearer {mint_supabase_token(sub=str(user.id))}"}


def test_banner_silent_while_any_candidate_unready(client, db, user):
    r = _run(db, user)
    _cand(db, user, str(r.sync_id), state="ready", person="person_free")
    _cand(db, user, str(r.sync_id), state="staged")           # one straggler blocks
    body = client.get("/gmail/ingest/pending-review", headers=_auth(user)).json()
    assert body["pending"] is False


def test_banner_surfaces_when_whole_batch_ready(client, db, user):
    r = _run(db, user)
    for _ in range(3):
        _cand(db, user, str(r.sync_id), state="ready", person="person_free")
    body = client.get("/gmail/ingest/pending-review", headers=_auth(user)).json()
    assert body["pending"] is True
    assert body["ready_count"] == 3


def test_banner_counts_ready_and_failed_as_reviewable(client, db, user):
    r = _run(db, user)
    _cand(db, user, str(r.sync_id), state="ready", person="person_free")
    _cand(db, user, str(r.sync_id), state="failed")           # Fix 2: reviewable, not hidden
    body = client.get("/gmail/ingest/pending-review", headers=_auth(user)).json()
    assert body["pending"] is True
    assert body["ready_count"] == 2                            # 1 ready + 1 failed to review


def test_banner_surfaces_when_only_failed(client, db, user):
    # Fix 2: an all-failed batch surfaces so the user can Retry/Dismiss (was silent).
    r = _run(db, user)
    _cand(db, user, str(r.sync_id), state="failed")
    body = client.get("/gmail/ingest/pending-review", headers=_auth(user)).json()
    assert body["pending"] is True
    assert body["ready_count"] == 1


def test_banner_silent_for_fresh_gmail_batch(client, db, user):
    # Intended Phase-1 intermediate state: a completed Gmail run whose candidates are all
    # 'staged' NEVER surfaces the banner (previously it surfaced instantly because
    # generation_total==0 made the settle clause vacuously true).
    r = _run(db, user)
    for _ in range(5):
        _cand(db, user, str(r.sync_id), state="staged")
    body = client.get("/gmail/ingest/pending-review", headers=_auth(user)).json()
    assert body["pending"] is False
