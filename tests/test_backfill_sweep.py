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


# ===========================================================================
# Phase 6b — whole-table widening (the 12 pre-rebuild rows this bucket missed)
# ===========================================================================

def _legacy_gmail_item(db, user, **over):
    """Shape of the 12 live rows: gmail, person_status='unknown',
    generation_status=None — the exact combination the old B5 filter excluded."""
    fields = dict(
        user_id=user.id, name="Legacy Retailer Tee", category="top",
        color_primary="black", source_type="gmail", image_url="https://cdn/retailer.jpg",
        generation_status=None, person_status="unknown",
    )
    fields.update(over)
    it = ClothingItem(**fields)
    db.add(it); db.commit(); db.refresh(it)
    return it


def test_whole_table_selection_catches_uncohorted_legacy_rows(db, user):
    """The old query required person_free/ready — a pre-rebuild row sitting at
    unknown/None was invisible to B5 entirely. It must be selected now."""
    legacy = _legacy_gmail_item(db, user)
    assert legacy.id in {r.id for r in sweep._b5_items_query(db).all()}

    report = sweep.classify(db)
    assert report.b5_unvalidated_items == 1


def test_dry_run_reports_no_image_and_non_clothing_subsets_without_mutating(db, user):
    _legacy_gmail_item(db, user, image_url=None, name="SHEIN Halter Top")
    _legacy_gmail_item(
        db, user, image_url=None, category="accessory",
        name="1pc Leopard Print Handbag Lunch Bag, Insulated Lunch Box",
        source_line_key=None,
    )
    scarf = _legacy_gmail_item(
        db, user, image_url=None, category="accessory",
        name="1pc Simple Striped Tassel Plaid Scarf",
    )

    report = sweep.classify(db)

    assert report.b5_unvalidated_items == 3
    assert report.b5_items_no_image == 3
    assert report.b5_items_suspected_non_clothing == 1   # the lunch bag only
    # A wearable accessory (scarf) is NOT auto-flagged — narrow, literal keyword hit only.
    assert not sweep._looks_like_non_clothing(scarf.name, scarf.category)
    # Nothing mutated.
    db.refresh(scarf)
    assert scarf.invariant_checked_at is None and scarf.archived_at is None


def test_no_image_item_generates_a_compliant_card(db, user, monkeypatch):
    it = _legacy_gmail_item(db, user, image_url=None, name="MUSERA Denim Jacket",
                            category="outerwear")
    import app.services.image_generation.generate_core as gc
    monkeypatch.setattr(
        gc, "generate_from_text",
        lambda **k: GenOutcome("ready", url="https://cdn/generated-jacket.png",
                               content_sha256="ff" * 32, verify_score=0.92),
    )
    monkeypatch.setattr(sweep, "_storage_from_env", lambda: None)

    report = sweep.run_sweep(db, execute=True, run_gmail_fill=False)

    db.refresh(it)
    assert report.regenerated == 1
    assert it.image_url == "https://cdn/generated-jacket.png"
    assert it.generation_status == "ready"
    assert it.person_status == "person_free"
    assert it.invariant_checked_at is not None


def test_no_image_item_never_left_imageless_and_displayable_on_miss(db, user, monkeypatch):
    """A no-image item that can't be generated goes terminal 'failed' — still
    imageless, but generation_status='failed' keeps the display gate masked. It is
    NEVER shown, and is reported (not silently vanished — stamped + terminal)."""
    from app.core.config import settings as cfg

    monkeypatch.setattr(cfg, "GENERATION_MAX_ATTEMPTS", 1)
    it = _legacy_gmail_item(db, user, image_url=None, name="SHEIN Halter Top")
    import app.services.image_generation.generate_core as gc
    monkeypatch.setattr(gc, "generate_from_text", lambda **k: GenOutcome("held"))
    monkeypatch.setattr(sweep, "_storage_from_env", lambda: None)

    report = sweep.run_sweep(db, execute=True, run_gmail_fill=False)

    db.refresh(it)
    assert report.terminal_failed == 1
    assert it.image_url is None
    assert it.generation_status == "failed"
    assert it.invariant_checked_at is not None    # converged — never re-billed again
    from app.models.closet import display_image_url
    assert display_image_url(it) is None          # imageless AND masked — never shown


def test_non_clothing_is_quarantined_never_imaged_never_auto_deleted(db, user, monkeypatch):
    junk = _legacy_gmail_item(
        db, user, image_url=None, category="accessory",
        name="1pc Korean Style Metal Hair Clip, Elegant Hairpin Barrette",
    )

    def _boom(**k):
        raise AssertionError("must never spend a generation call on quarantined junk")

    import app.services.image_generation.generate_core as gc
    monkeypatch.setattr(gc, "generate_from_text", _boom)
    monkeypatch.setattr(sweep, "verify_image", lambda **k: (_ for _ in ()).throw(
        AssertionError("must never verify quarantined junk")))

    report = sweep.run_sweep(db, execute=True, run_gmail_fill=False)

    db.refresh(junk)
    assert len(report.quarantined) == 1
    assert report.quarantined[0]["id"] == str(junk.id)
    assert report.quarantined[0]["name"] == junk.name
    assert report.quarantined[0]["category"] == "accessory"
    assert "hairpin" in report.quarantined[0]["reason"] or "hair" in report.quarantined[0]["reason"]
    assert junk.archived_at is not None            # quarantined (operative hide)
    assert junk.is_non_clothing is True            # EXPLICIT, provable marker (0038)
    assert junk.quarantine_reason is not None
    assert junk.invariant_checked_at is not None   # converged
    assert junk.image_url is None                  # STILL exists in the DB — not deleted
    from app.services.closet_service import list_closet_items
    assert junk.id not in {i.id for i in list_closet_items(db, user.id)}  # hidden from grid


def test_quarantine_idempotent_second_run_zero_calls(db, user, monkeypatch):
    _legacy_gmail_item(
        db, user, image_url=None, category="accessory",
        name="1pc Leopard Print Handbag Lunch Bag, Insulated",
    )
    calls = {"n": 0}
    import app.services.image_generation.generate_core as gc
    monkeypatch.setattr(gc, "generate_from_text", lambda **k: calls.__setitem__("n", calls["n"] + 1) or GenOutcome("held"))

    sweep.run_sweep(db, execute=True, run_gmail_fill=False)
    sweep.run_sweep(db, execute=True, run_gmail_fill=False)

    assert calls["n"] == 0   # never touched generation — quarantined on first pass, forever


def test_list_closet_items_excludes_archived(db, user):
    from app.services.closet_service import list_closet_items

    visible = ClothingItem(user_id=user.id, name="Visible Tee", category="top")
    hidden = ClothingItem(
        user_id=user.id, name="Archived Tee", category="top",
        archived_at=sweep._now_utc(),
    )
    db.add_all([visible, hidden]); db.commit()

    ids = {i.id for i in list_closet_items(db, user.id)}
    assert visible.id in ids
    assert hidden.id not in ids


# ===========================================================================
# Phase 6b — quarantined + fail-closed-masked rows excluded from EVERY display
# surface: closet grid, item detail, compose (stylist id-resolution + serialize),
# today's-look, collage.
# ===========================================================================

def _quarantined_and_masked(db, user):
    """One quarantined row (is_non_clothing) + one fail-closed image-null row
    (generation_status='failed', never quarantined) — both must be invisible
    everywhere, for different reasons."""
    quarantined = ClothingItem(
        user_id=user.id, name="Quarantined Lunch Bag", category="accessory",
        source_type="gmail", image_url=None, archived_at=sweep._now_utc(),
        is_non_clothing=True, quarantine_reason="non_clothing_keyword:lunch bag",
        invariant_checked_at=sweep._now_utc(),
    )
    masked = ClothingItem(
        user_id=user.id, name="Terminal Failed Item", category="top",
        source_type="gmail", image_url=None, generation_status="failed",
        person_status="unknown", invariant_checked_at=sweep._now_utc(),
    )
    db.add_all([quarantined, masked]); db.commit()
    db.refresh(quarantined); db.refresh(masked)
    return quarantined, masked


def test_quarantined_and_masked_excluded_from_closet_grid(db, user):
    from app.services.closet_service import list_closet_items

    quarantined, masked = _quarantined_and_masked(db, user)
    ids = {i.id for i in list_closet_items(db, user.id)}
    assert quarantined.id not in ids
    # The masked (non-archived) row DOES list — but must show no image (checked below).
    assert masked.id in ids


def test_quarantined_excluded_from_item_detail(db, user):
    from app.services.closet_service import get_closet_item_by_id

    quarantined, masked = _quarantined_and_masked(db, user)
    assert get_closet_item_by_id(db, user.id, quarantined.id) is None
    assert get_closet_item_by_id(db, user.id, masked.id) is not None  # exists, just imageless


def test_quarantined_excluded_from_compose_id_resolution(db, user):
    from app.services.stylist.retrieval import get_owned_items

    quarantined, masked = _quarantined_and_masked(db, user)
    resolved = get_owned_items(db, user.id, [quarantined.id, masked.id])
    resolved_ids = {i.id for i in resolved}
    assert quarantined.id not in resolved_ids
    assert masked.id in resolved_ids   # resolvable as a row; serialize masks its image


def test_both_rows_show_no_image_via_serialize_and_display_gate(db, user):
    from app.models.closet import display_image_url
    from app.services.stylist.retrieval import serialize_item

    quarantined, masked = _quarantined_and_masked(db, user)
    assert display_image_url(quarantined) is None
    assert display_image_url(masked) is None
    assert serialize_item(quarantined)["imageUrl"] is None
    assert serialize_item(masked)["imageUrl"] is None


def test_both_rows_excluded_from_todays_look_owned_set(db, user):
    from app.services.stylist.todays_look import _load_owned

    quarantined, masked = _quarantined_and_masked(db, user)
    owned_ids = {i.id for i in _load_owned(db, user.id)}
    assert quarantined.id not in owned_ids     # archived -> not even loaded
    assert masked.id in owned_ids              # loaded, but usable_image_url masks it


def test_both_rows_unusable_in_collage(db, user):
    from app.services.stylist.collage import usable_image_url

    quarantined, masked = _quarantined_and_masked(db, user)
    assert usable_image_url(quarantined) is None
    assert usable_image_url(masked) is None


# ===========================================================================
# Observability — the sweep's regenerations stamp generation_provider + cost
# ===========================================================================

def test_sweep_item_regen_stamps_provider_and_cost(db, user, monkeypatch):
    """A with-image item that fails verify-v2 and is regenerated by the sweep must
    record which provider produced the new card (was null before this fix)."""
    it = _item(db, user, generation_provider=None, generation_cost_usd=None)
    _patch_seams(
        monkeypatch, verdict=_ok_verdict(framing_ok=False),
        gen_outcome=GenOutcome("ready", url="https://cdn/regen.png",
                               content_sha256="aa" * 32, verify_score=0.9,
                               cost_usd=0.045, provider="flux2_pro"),
    )
    sweep.run_sweep(db, execute=True, run_gmail_fill=False)

    db.refresh(it)
    assert it.generation_status == "ready"
    assert it.image_url == "https://cdn/regen.png"
    assert it.generation_provider == "flux2_pro"          # stamped, not null
    assert float(it.generation_cost_usd) == pytest.approx(0.045)


def test_sweep_no_image_item_stamps_provider(db, user, monkeypatch):
    """A no-image item generated (t2i) by the sweep stamps its provider too."""
    it = _item(db, user, image_url=None, generation_status=None,
               source_type="gmail", person_status="unknown")
    monkeypatch.setattr(sweep, "_download_bytes", lambda url: (b"img", "image/png"))
    monkeypatch.setattr(sweep, "verify_image", lambda **k: _ok_verdict())
    monkeypatch.setattr(sweep, "_storage_from_env", lambda: None)
    import app.services.image_generation.generate_core as gc
    monkeypatch.setattr(
        gc, "generate_from_text",
        lambda **k: GenOutcome("ready", url="https://cdn/t2i.png",
                               content_sha256="bb" * 32, verify_score=0.9,
                               cost_usd=0.134, provider="nano_banana"),
    )
    sweep.run_sweep(db, execute=True, run_gmail_fill=False)

    db.refresh(it)
    assert it.generation_status == "ready"
    assert it.generation_provider == "nano_banana"
    assert float(it.generation_cost_usd) == pytest.approx(0.134)
