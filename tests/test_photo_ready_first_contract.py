"""Photo-seam Phase 3 — the photo G2/G3 contract.

Gates:
  * G2 per-zone accounting: N selected zones => N candidates, none silently dropped —
    a zone that can't proceed (no cutout / generation unavailable) is staged as a
    TERMINAL 'failed' candidate, traceable by source_line_key, and the response
    accounts for every zone (selected == staged + failed + duplicate-photo zones).
  * G3 whole-batch settle (shared review_service.settle_counts): review surfaces only
    when zero candidates are mid-pipeline; needs-size cards count as
    settled-but-reviewable; the deck serves only ready + needs-size.
  * Needs-size surfacing: a verified card held only by a missing size appears in the
    deck, doesn't block the batch, and resolves to 'ready' when the size is supplied
    at confirm.
  * Strand-killing: budget-denied residue is heal-eligible 'pending_retry' (healed by
    the sweep), disarmed commits settle immediately as 'failed', and the status poll
    reports the settle + kicks the strand heal.
"""
from __future__ import annotations

import io
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import Base, SessionLocal, engine
from app.gmail_closet.review_service import (
    confirm_candidates,
    list_pending_candidates,
    settle_counts,
)
from app.models import ClothingItem, IngestCandidate, IngestRun, User
from app.photo_closet import generation_service as gen
from app.photo_closet import ingest_service
from app.photo_closet.detection import DetectionResult, GarmentRegion
from app.photo_closet.ingest_service import PhotoSelection, _source_line_key
from app.services.image_generation.generate_core import GenOutcome
from tests._authutil import mint_supabase_token
from app.utils.image_validation import validate_and_sanitize
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
    u = User(email="contract@example.com", hashed_password="x", display_name="C")
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture(autouse=True)
def _fake_upload(monkeypatch):
    monkeypatch.setattr(
        ingest_service, "store_cutout",
        lambda sc, uid, cut: "https://blob.example/cutout.jpg" if cut else None,
    )


def _sanitized(color=(120, 30, 30)):
    img = Image.new("RGB", (128, 128), color)
    buf = io.BytesIO(); img.save(buf, "JPEG")
    return validate_and_sanitize(buf.getvalue())


def _garment(name, cat="top", box=(0, 0, 1000, 1000), color="red"):
    return GarmentRegion(
        name=name, category=cat, color=color, box_2d=list(box), confidence_overall=0.9,
    )


def _detect_one(db, user, sanitized, detection):
    outcomes = ingest_service.run_photo_detect(
        db, user.id, [sanitized],
        detect=lambda **kw: detection,
    )
    assert len(outcomes) == 1
    return outcomes[0]


def _stage_row(db, user, sync_id, **over):
    fields = dict(
        user_id=user.id, sync_id=sync_id, source_type="photo", status="pending",
        image_url="https://blob.example/cut.jpg", image_status="user_uploaded",
        name="Crew Tee", category="top", color="red", size="M",
        pipeline_state="staged", person_status="person_free",
    )
    fields.update(over)
    c = IngestCandidate(**fields)
    db.add(c); db.commit(); db.refresh(c)
    return c


# ===========================================================================
# G2 — per-zone accounting
# ===========================================================================

def test_every_selected_zone_is_accounted_for(db, user, monkeypatch):
    """3 zones selected, one cutout unusable -> 2 viable + 1 TERMINAL 'failed'
    candidate. selected == staged + failed; the failed zone is traceable and the
    batch's settle condition is reachable."""
    img = _sanitized()
    bad_box = [20, 600, 900, 990]
    detection = DetectionResult(person_count=0, garments=[
        _garment("Red Tee", "top", (50, 50, 500, 600)),
        _garment("Blue Jeans", "bottom", (500, 80, 980, 560), color="blue"),
        _garment("Green Coat", "outerwear", bad_box, color="green"),
    ])
    out = _detect_one(db, user, img, detection)

    real_build = ingest_service.build_cutout

    def _flaky_cutout(*, original, box_2d, mask_b64=None):
        if list(box_2d) == bad_box:
            return None  # unusable zone
        return real_build(original=original, box_2d=box_2d, mask_b64=mask_b64)

    monkeypatch.setattr(ingest_service, "build_cutout", _flaky_cutout)

    res = ingest_service.run_photo_commit(
        db, user.id, None, {img.sha256: img},
        [PhotoSelection(session_id=out.session_id, selected_region_ids=[0, 1, 2])],
    )

    assert res.selected == 3
    assert res.staged == 2
    assert res.failed == 1
    assert res.selected == res.staged + res.failed

    cands = db.query(IngestCandidate).filter(IngestCandidate.user_id == user.id).all()
    assert len(cands) == 3  # N zones -> N candidates, none dropped
    failed = [c for c in cands if c.pipeline_state == "failed"]
    assert len(failed) == 1
    assert failed[0].source_line_key == _source_line_key(img.sha256, bad_box)
    assert failed[0].generation_status == "failed"

    # The failed zone neither appears in the deck nor blocks the settle forever.
    counts = settle_counts(db, user.id, res.sync_id)
    assert counts.failed == 1 and counts.unsettled == 2  # viable zones still in flight


def test_disarmed_commit_fails_zones_and_settles_immediately(db, user):
    """Generation unavailable -> a compliant card can never be produced: zones go
    TERMINAL 'failed' (visible), the batch settles at once, nothing strands."""
    img = _sanitized()
    out = _detect_one(db, user, img, DetectionResult(person_count=0, garments=[
        _garment("Red Tee", "top", (50, 50, 500, 600)),
        _garment("Blue Jeans", "bottom", (500, 80, 980, 560), color="blue"),
    ]))

    res = ingest_service.run_photo_commit(
        db, user.id, None, {img.sha256: img},
        [PhotoSelection(session_id=out.session_id, selected_region_ids=[0, 1])],
        generation_available=False,
    )

    assert res.selected == 2 and res.staged == 0 and res.failed == 2
    counts = settle_counts(db, user.id, res.sync_id)
    assert counts.settled and counts.failed == 2 and counts.reviewable == 0
    # All-failed batch: deck empty, run completed (defer skipped on staged=0).
    assert list_pending_candidates(db, user.id, sync_id=res.sync_id) == []
    run = db.query(IngestRun).filter(IngestRun.sync_id == res.sync_id).one()
    assert run.status == "completed"


# ===========================================================================
# G3 — whole-batch settle + deck admission
# ===========================================================================

def test_settle_requires_all_terminal_and_deck_serves_only_ready(db, user):
    sync = str(uuid4())
    ready = _stage_row(db, user, sync, pipeline_state="ready",
                       generation_status="ready",
                       generated_image_url="https://cdn/card.png",
                       source_line_key="z-ready")
    _stage_row(db, user, sync, pipeline_state="failed",
               generation_status="failed", source_line_key="z-failed")
    inflight = _stage_row(db, user, sync, pipeline_state="image_pending",
                          generation_status="generating", source_line_key="z-flight")

    counts = settle_counts(db, user.id, sync)
    assert not counts.settled and counts.unsettled == 1

    deck = list_pending_candidates(db, user.id, sync_id=sync)
    assert [d["candidate_id"] for d in deck] == [str(ready.id)]  # only 'ready'

    # The straggler goes terminal -> the batch settles; failed neither blocks nor counts.
    inflight.pipeline_state = "failed"
    inflight.generation_status = "failed"
    db.commit()
    counts = settle_counts(db, user.id, sync)
    assert counts.settled and counts.ready == 1 and counts.failed == 2
    assert counts.reviewable == 1


# ===========================================================================
# Needs-size — surfaces, doesn't block, resolves to ready on size supply
# ===========================================================================

def _needs_size_row(db, user, sync, slk="z-needs-size"):
    return _stage_row(
        db, user, sync, size=None, pipeline_state="verified_clean",
        generation_status="ready", generated_image_url="https://cdn/card.png",
        source_line_key=slk,
    )


def test_needs_size_surfaces_and_never_blocks_the_batch(db, user):
    sync = str(uuid4())
    c = _needs_size_row(db, user, sync)

    counts = settle_counts(db, user.id, sync)
    assert counts.settled            # needs-size never blocks the batch
    assert counts.needs_size == 1 and counts.reviewable == 1

    deck = list_pending_candidates(db, user.id, sync_id=sync)
    assert len(deck) == 1
    assert deck[0]["candidate_id"] == str(c.id)
    assert deck[0]["needs_size"] is True
    assert deck[0]["generated_image_url"] == "https://cdn/card.png"


def test_needs_size_resolves_to_ready_when_size_supplied_at_confirm(db, user, monkeypatch):
    from app.gmail_closet import review_service

    sync = str(uuid4())
    c = _needs_size_row(db, user, sync)

    # The real upsert is a Postgres-only statement (pg_insert + xmax RETURNING) —
    # stub it on SQLite and capture what the item WOULD be written with.
    seen = {}

    def _stub_upsert(db_, uid, cand, ga_id, facts=None):
        seen["used_card"] = review_service._used_generated_card(cand)
        seen["size"] = cand.size
        return review_service.WrittenItem(
            clothing_item_id=str(uuid4()), candidate_id=str(cand.id),
            name=cand.name, source_line_key=cand.source_line_key, inserted=True,
        )

    monkeypatch.setattr(review_service, "_upsert_clothing_item", _stub_upsert)

    result = confirm_candidates(
        db, user.id, accepted=[str(c.id)], edits={str(c.id): {"size": "M"}},
    )

    db.refresh(c)
    assert c.size == "M"
    assert c.pipeline_state == "ready"      # completed through THE shared ready writer
    assert c.status == "accepted"
    assert seen["size"] == "M"
    assert seen["used_card"] is True        # the item gets the verified card, not the crop
    assert result.accepted_count == 1


def test_verified_clean_without_card_still_blocks(db, user):
    """A bare verified_clean row that does NOT qualify as needs-size (no card) keeps
    blocking the settle — needs-size is a narrow, card-backed exception."""
    sync = str(uuid4())
    _stage_row(db, user, sync, size=None, pipeline_state="verified_clean",
               generation_status=None, generated_image_url=None,
               source_line_key="z-clean-no-card")
    counts = settle_counts(db, user.id, sync)
    assert not counts.settled and counts.needs_size == 0
    assert list_pending_candidates(db, user.id, sync_id=sync) == []


# ===========================================================================
# Strand-killing — budget residue heals; status poll reports settle + kicks heal
# ===========================================================================

def test_budget_residue_is_healed_by_the_sweep(db, user, monkeypatch):
    """The Phase-3 budget shape ('pending_retry' + 'image_pending' + crop present) is
    exactly what run_generation_self_heal re-selects; a verified pass completes it
    through the shared ready writer."""
    sync = uuid4()
    c = _stage_row(db, user, str(sync), pipeline_state="image_pending",
                   generation_status="pending_retry", source_line_key="z-budget")

    monkeypatch.setattr(
        gen, "_generate_from_crop",
        lambda **kw: gen._HealOutcome("ready", url="https://cdn/healed.png",
                                      content_sha256="cc" * 32, verify_score=0.9),
    )
    stats = gen.run_generation_self_heal(user.id, db)

    db.refresh(c)
    assert stats.ready == 1
    assert c.generation_status == "ready"
    assert c.generated_image_url == "https://cdn/healed.png"
    assert c.pipeline_state == "ready" and c.person_status == "person_free"


def test_status_poll_reports_settle_and_kicks_strand_heal(db, user, monkeypatch):
    """A completed-but-unsettled photo run: the status poll reports settled=False,
    demotes stale 'generating' residue to 'pending_retry', and dispatches the
    debounced self-heal so the settle condition stays reachable."""
    import app.api.routes.gmail_ingest as gi

    sync = uuid4()
    db.add(IngestRun(sync_id=sync, user_id=user.id, status="completed",
                     source_type="photo"))
    db.commit()
    stale = _stage_row(db, user, str(sync), pipeline_state="image_pending",
                       generation_status="generating", source_line_key="z-stale")

    monkeypatch.setattr(gen, "generation_armed", lambda: True)
    kicked = []
    monkeypatch.setattr(gen, "self_heal_background", lambda uid: kicked.append(uid))
    gi._heal_kick_last.clear()  # fresh debounce window for the test

    client = TestClient(app)
    token = mint_supabase_token(sub=str(user.id))
    resp = client.get(
        f"/gmail/ingest/status?sync_id={sync}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["progress"]["settled"] is False

    db.refresh(stale)
    assert stale.generation_status == "pending_retry"   # stale 'generating' demoted
    assert kicked == [str(user.id)]                     # heal dispatched (debounced)

    # Second poll inside the debounce window: no second dispatch.
    resp = client.get(
        f"/gmail/ingest/status?sync_id={sync}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert kicked == [str(user.id)]
