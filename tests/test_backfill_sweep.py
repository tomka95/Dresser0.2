"""Photo-seam Phase 6 — the invariant backfill sweep.

Gates:
  * dry-run classification counts every bucket correctly and mutates NOTHING;
  * B1 ready+person rows: v2 pass repairs state in place; v2 fail knocks out of
    'ready' and regenerates through the seam (restored only on a full pass);
  * B2 stranded residue normalized to heal-eligible;
  * B3 legacy crops purged retroactively (P5 rules: photo_items deleted, foreign
    unlinked);
  * B5 unvalidated images: pass -> marker; fail -> demoted (fail-closed, masked) ->
    regenerated inline; attempt ceiling -> terminal 'failed';
  * IDEMPOTENT: a second run re-verifies nothing (marker honored) — no double-charge.
"""
from __future__ import annotations

import uuid
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import Base, SessionLocal, engine
from app.gmail_closet.image_verify import VerifyVerdict
from app.models import ClothingItem, IngestCandidate, User
from app.photo_closet import backfill_sweep as sweep
from app.photo_closet import generation_service as gen
from app.services.image_generation.generate_core import GenOutcome


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
    u = User(email="sweep@example.com", hashed_password="x", display_name="S")
    db.add(u); db.commit(); db.refresh(u)
    return u


CROP = "https://cdn.example/storage/v1/object/public/b/photo_items/u/crop.jpg"
CARD = "https://cdn.example/storage/v1/object/public/b/generated_items/u/card.png"


def _cand(db, user, **over):
    fields = dict(
        user_id=user.id, sync_id=uuid4(), source_type="photo", status="pending",
        source_line_key=f"k-{uuid.uuid4().hex[:8]}",
        image_url=CROP, image_status="user_uploaded",
        name="Crew Tee", category="top", color="red", size="M",
        pipeline_state="staged", person_status="person_free",
    )
    fields.update(over)
    c = IngestCandidate(**fields)
    db.add(c); db.commit(); db.refresh(c)
    return c


def _item(db, user, **over):
    fields = dict(
        user_id=user.id, name="Crew Tee", category="top", color_primary="red",
        source_type="photo", image_url=CARD, generation_status="ready",
        person_status="person_free",
    )
    fields.update(over)
    it = ClothingItem(**fields)
    db.add(it); db.commit(); db.refresh(it)
    return it


def _ok_verdict(**over):
    base = dict(matches=True, garment_ok=True, color_ok=True, score=0.9,
                reason="ok", model="m")
    base.update(over)
    return VerifyVerdict(**base)


def _patch_seams(monkeypatch, *, verdict, gen_outcome=None):
    monkeypatch.setattr(sweep, "_download_bytes", lambda url: (b"img", "image/png"))
    monkeypatch.setattr(sweep, "verify_image", lambda **k: verdict)
    monkeypatch.setattr(
        sweep, "generate_from_reference_bytes",
        lambda **k: gen_outcome
        or GenOutcome("ready", url="https://cdn/new-card.png",
                      content_sha256="ee" * 32, verify_score=0.9),
    )
    monkeypatch.setattr(sweep, "_storage_from_env", lambda: None)


# ===========================================================================
# Dry run — classification only, zero mutation
# ===========================================================================

def test_dry_run_classifies_and_mutates_nothing(db, user, monkeypatch):
    b1 = _cand(db, user, pipeline_state="ready", person_status="person_present",
               generation_status="ready", generated_image_url=CARD)
    _cand(db, user, pipeline_state="staged", generation_status="pending_retry",
          source_line_key="b2")
    _cand(db, user, source_type="gmail", image_url=None, image_status="pending",
          person_status="unknown", source_line_key="b4")
    _item(db, user)

    monkeypatch.setattr(
        sweep, "verify_image",
        lambda **k: pytest.fail("dry-run must not verify"),
    )
    report = sweep.run_sweep(db, execute=False)

    assert report.executed is False
    assert report.b1_ready_person_violations == 1
    assert report.b2_stranded_residue == 1
    assert report.b4_gmail_frozen == 1
    # b1's candidate carries an unvalidated card; the item is unvalidated too.
    assert report.b5_unvalidated_candidates == 1
    assert report.b5_unvalidated_items == 1
    assert report.projected_verify_calls == 2
    db.refresh(b1)
    assert b1.pipeline_state == "ready" and b1.person_status == "person_present"


# ===========================================================================
# B1 — ready + person violations
# ===========================================================================

def test_b1_pass_repairs_state_in_place(db, user, monkeypatch):
    c = _cand(db, user, pipeline_state="ready", person_status="person_present",
              generation_status="ready", generated_image_url=CARD, image_url=None)
    _patch_seams(monkeypatch, verdict=_ok_verdict())

    report = sweep.run_sweep(db, execute=True, run_gmail_fill=False)

    db.refresh(c)
    assert report.revalidated_pass == 1
    assert c.pipeline_state == "ready"                 # stays ready — card is compliant
    assert c.person_status == "person_free"            # state repaired to the truth
    assert c.invariant_checked_at is not None


def test_b1_fail_knocks_out_of_ready_and_regenerates(db, user, monkeypatch):
    c = _cand(db, user, pipeline_state="ready", person_status="person_present",
              generation_status="ready", generated_image_url=CARD, image_url=None)
    _patch_seams(monkeypatch, verdict=_ok_verdict(person_present=True))

    report = sweep.run_sweep(db, execute=True, run_gmail_fill=False)

    db.refresh(c)
    assert report.revalidated_fail == 1 and report.regenerated == 1
    assert c.generated_image_url == "https://cdn/new-card.png"
    assert c.pipeline_state == "ready"                 # restored ONLY via the full pass
    assert c.person_status == "person_free"
    assert c.invariant_checked_at is not None


# ===========================================================================
# B2 — stranded residue normalized
# ===========================================================================

def test_b2_residue_normalized_to_heal_eligible(db, user, monkeypatch):
    stuck = _cand(db, user, pipeline_state="staged", generation_status="pending_retry")
    stuck_null = _cand(db, user, pipeline_state="staged", generation_status=None,
                       source_line_key="b2-null")
    _patch_seams(monkeypatch, verdict=_ok_verdict())

    report = sweep.run_sweep(db, execute=True, run_gmail_fill=False)

    db.refresh(stuck); db.refresh(stuck_null)
    assert report.residue_normalized == 2
    for c in (stuck, stuck_null):
        assert c.generation_status == "pending_retry"
        assert c.pipeline_state == "image_pending"


# ===========================================================================
# B3 — legacy crops purged retroactively
# ===========================================================================

def test_b3_purges_legacy_ready_crops(db, user, monkeypatch):
    c = _cand(db, user, pipeline_state="ready", person_status="person_free",
              generation_status="ready", generated_image_url=CARD,
              invariant_checked_at=gen._now_utc())  # already validated -> not B5
    deleted = []

    class _Storage:
        def delete_object(self, url):
            deleted.append(url)
            return True

    import app.utils.image_blob_store as blob_store
    monkeypatch.setattr(blob_store, "delete_by_url", lambda url: 1)
    _patch_seams(monkeypatch, verdict=_ok_verdict())
    monkeypatch.setattr(sweep, "_storage_from_env", lambda: _Storage())

    report = sweep.run_sweep(db, execute=True, run_gmail_fill=False)

    db.refresh(c)
    assert report.crops_purged == 1
    assert c.image_url is None                          # display-unreachable
    assert deleted == [CROP]                            # our photo_items blob deleted
    assert c.generated_image_url == CARD                # the card untouched


# ===========================================================================
# B5 — re-validation: fail-closed demotion, inline regen, ceiling, idempotency
# ===========================================================================

def test_b5_item_fail_regenerates_and_restores(db, user, monkeypatch):
    it = _item(db, user)
    _patch_seams(monkeypatch, verdict=_ok_verdict(framing_ok=False))

    report = sweep.run_sweep(db, execute=True, run_gmail_fill=False)

    db.refresh(it)
    assert report.revalidated_fail == 1 and report.regenerated == 1
    assert it.image_url == "https://cdn/new-card.png"
    assert it.generation_status == "ready"
    assert it.invariant_checked_at is not None


def test_b5_item_fail_with_regen_miss_is_masked_then_terminal(db, user, monkeypatch):
    monkeypatch.setattr(settings, "GENERATION_MAX_ATTEMPTS", 1)
    it = _item(db, user)
    _patch_seams(monkeypatch, verdict=_ok_verdict(background_offwhite_ok=False),
                 gen_outcome=GenOutcome("held"))

    report = sweep.run_sweep(db, execute=True, run_gmail_fill=False)

    db.refresh(it)
    assert report.demoted == 1 and report.terminal_failed == 1
    assert it.generation_status == "failed"             # ceiling burned, fail-closed
    from app.models.closet import display_image_url
    assert display_image_url(it) is None                # never displays the bad image


def test_b5_gmail_item_fail_is_masked_despite_person_free(db, user, monkeypatch):
    """The Phase-6 display-gate extension: a gmail item demoted for regeneration is
    masked even though person_status='person_free'."""
    it = _item(db, user, source_type="gmail", generation_status=None,
               image_url="https://cdn/retailer.jpg")
    _patch_seams(monkeypatch, verdict=_ok_verdict(extra_items_present=True),
                 gen_outcome=GenOutcome("held"))

    sweep.run_sweep(db, execute=True, run_gmail_fill=False)

    db.refresh(it)
    assert it.generation_status == "pending_retry"
    from app.models.closet import display_image_url
    assert display_image_url(it) is None


def test_sweep_is_idempotent_no_double_charge(db, user, monkeypatch):
    it = _item(db, user)
    c = _cand(db, user, pipeline_state="ready", person_status="person_free",
              generation_status="ready", generated_image_url=CARD, image_url=None)
    calls = {"verify": 0}

    def _verify(**k):
        calls["verify"] += 1
        return _ok_verdict()

    _patch_seams(monkeypatch, verdict=_ok_verdict())
    monkeypatch.setattr(sweep, "verify_image", _verify)

    r1 = sweep.run_sweep(db, execute=True, run_gmail_fill=False)
    assert r1.revalidated_pass == 2 and calls["verify"] == 2

    r2 = sweep.run_sweep(db, execute=True, run_gmail_fill=False)
    assert r2.revalidated_pass == 0
    assert calls["verify"] == 2                        # marker honored: zero re-billing


def test_verify_budget_exhaustion_leaves_resume_target(db, user, monkeypatch):
    it = _item(db, user)
    _patch_seams(monkeypatch, verdict=VerifyVerdict(
        False, False, False, 0.0, "budget exhausted", "m", skipped=True))

    report = sweep.run_sweep(db, execute=True, run_gmail_fill=False)

    db.refresh(it)
    assert report.verify_skipped == 1
    assert it.invariant_checked_at is None             # still a target next run
    assert it.generation_status == "ready"             # untouched — nothing demoted
