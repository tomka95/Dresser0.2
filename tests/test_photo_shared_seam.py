"""Photo-seam Phase 1 — the photo pipeline runs the ONE shared generation seam.

Gates:
  * run_photo_generation / self-heal / regenerate delegate generate→verify→store to
    generate_core.generate_from_reference_bytes (the seam the Gmail pipeline runs) —
    no photo-local ladder/verify/store remains.
  * Shared product_image_cache participation, BRANDED items only: cache-hit serves a
    card with zero generation calls; a verified branded card is promoted; unbranded
    personal garments never touch the cache (identity too weak + personal-content
    cross-user leak).
  * The SHARED readiness invariant (services.readiness.mark_candidate_ready): a photo
    candidate is 'ready' ⟺ verified card + person_free + complete tags. A verified
    card with incomplete tags rests at 'verified_clean' (masked), never leaks.
  * Stage-time canonicalize-lite: size defaults from the user's onboarding facts.
  * Re-stage terminal immutability: a ready row re-committed stays ready AND goes
    person_free with its card (no ready+person_present resurrection).
  * Regenerate steering reaches the shared core.
"""
from __future__ import annotations

import uuid
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, engine
from app.models import IngestCandidate, IngestRun, StyleProfile, User
from app.photo_closet import generation_service as gen
from app.photo_closet.ingest_service import _stage_candidate
from app.services import readiness
from app.services.image_generation import generate_core as core
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
    u = User(email="seam@example.com", hashed_password="x", display_name="S")
    db.add(u); db.commit(); db.refresh(u)
    return u


def _stage(db, user, sync_id, **over):
    fields = dict(
        user_id=user.id, sync_id=sync_id, source_type="photo", status="pending",
        image_url="https://blob/cut.jpg", image_status="user_uploaded",
        name="Crew Tee", category="top", color="red", size="M",
        generation_status=None,
    )
    fields.update(over)
    c = IngestCandidate(**fields)
    db.add(c); db.commit(); db.refresh(c)
    return c


def _run_row(db, user, sync_id):
    r = IngestRun(sync_id=sync_id, user_id=user.id, status="running", source_type="photo")
    db.add(r); db.commit()
    return r


class _G:
    """GarmentRegion-shaped stub for _stage_candidate."""
    name = "Crew Tee"
    brand = None
    color = "white"
    confidence_overall = 0.9

    class category:
        value = "top"

    class confidence:
        name = brand = category = color = 0.9


# ===========================================================================
# 1. Delegation — the photo worker runs the shared core seam
# ===========================================================================

def test_photo_generation_delegates_to_shared_core(db, user, monkeypatch):
    sync = uuid4(); _run_row(db, user, sync)
    c = _stage(db, user, sync)
    monkeypatch.setattr(gen, "_download_bytes", lambda url: (b"cut", "image/jpeg"))

    seen = {}

    def _fake_core(**kw):
        seen.update(kw)
        return GenOutcome("ready", url="https://blob/card.png",
                          content_sha256="ff" * 32, verify_score=0.9, cost_usd=0.045)

    monkeypatch.setattr(gen, "generate_from_reference_bytes", _fake_core)

    stats = gen.run_photo_generation(user.id, db, sync)

    db.refresh(c)
    assert stats.ready == 1
    assert c.generated_image_url == "https://blob/card.png"
    assert c.generation_status == "ready"
    assert c.pipeline_state == "ready" and c.person_status == "person_free"
    # The shared core received the candidate's attributes + the crop bytes.
    assert seen["reference_bytes"] == b"cut"
    assert seen["name"] == "Crew Tee" and seen["category"] == "top"
    assert seen["ladder"] is None  # None -> the core's own (shared) ladder


def test_no_photo_local_ladder_or_store_remains(db):
    # The parallel photo implementation is GONE: one ladder, one armed(), one store.
    assert not hasattr(gen, "_GENERATION_LADDER")
    assert not hasattr(gen, "_store_generated")
    assert not hasattr(gen, "verify_generated_image")  # verify lives in the core seam
    assert gen.generation_armed() == core.generation_armed()


# ===========================================================================
# 2. Shared product_image_cache — branded items only
# ===========================================================================

def test_branded_cache_hit_serves_card_without_generation(db, user, monkeypatch):
    sync = uuid4(); _run_row(db, user, sync)
    c = _stage(db, user, sync, brand="Uniqlo")
    monkeypatch.setattr(gen, "lookup_verified", lambda ck: "https://cache/card.png" if ck else None)

    def _boom(**kw):  # generation must never run on a cache hit
        raise AssertionError("generation called despite cache hit")

    monkeypatch.setattr(gen, "generate_from_reference_bytes", _boom)

    stats = gen.run_photo_generation(user.id, db, sync)

    db.refresh(c)
    assert stats.ready == 1 and stats.cost_usd == 0.0
    assert c.generated_image_url == "https://cache/card.png"
    assert c.pipeline_state == "ready" and c.person_status == "person_free"


def test_unbranded_never_touches_cache(db, user, monkeypatch):
    sync = uuid4(); _run_row(db, user, sync)
    _stage(db, user, sync, brand=None)
    monkeypatch.setattr(gen, "_download_bytes", lambda url: (b"cut", "image/jpeg"))

    lookups, promotes = [], []
    monkeypatch.setattr(gen, "lookup_verified", lambda ck: lookups.append(ck) or None)
    monkeypatch.setattr(gen, "promote_verified", lambda **kw: promotes.append(kw) or True)
    monkeypatch.setattr(
        gen, "generate_from_reference_bytes",
        lambda **kw: GenOutcome("ready", url="https://blob/card.png",
                                content_sha256="aa" * 32, verify_score=0.9),
    )

    gen.run_photo_generation(user.id, db, sync)

    # Unbranded -> key is None (lookup no-ops) and NOTHING is promoted.
    assert lookups == [None]
    assert promotes == []


def test_branded_verified_card_promotes_to_shared_cache(db, user, monkeypatch):
    sync = uuid4(); _run_row(db, user, sync)
    _stage(db, user, sync, brand="Uniqlo")
    monkeypatch.setattr(gen, "_download_bytes", lambda url: (b"cut", "image/jpeg"))
    monkeypatch.setattr(gen, "lookup_verified", lambda ck: None)
    promotes = []
    monkeypatch.setattr(gen, "promote_verified", lambda **kw: promotes.append(kw) or True)
    monkeypatch.setattr(
        gen, "generate_from_reference_bytes",
        lambda **kw: GenOutcome("ready", url="https://blob/card.png",
                                content_sha256="aa" * 32, verify_score=0.88),
    )

    gen.run_photo_generation(user.id, db, sync)

    assert len(promotes) == 1
    p = promotes[0]
    assert p["brand"] == "Uniqlo" and p["image_url"] == "https://blob/card.png"
    assert p["source_tier"] == "generated" and p["verify_score"] == 0.88


# ===========================================================================
# 3. The SHARED readiness invariant on the photo path
# ===========================================================================

def test_verified_card_with_missing_size_rests_at_verified_clean(db, user, monkeypatch):
    """No size, no onboarding facts -> the card lands but 'ready' is withheld (masked),
    exactly the Gmail rule. generation_status='ready' keeps it out of re-selection."""
    sync = uuid4(); _run_row(db, user, sync)
    c = _stage(db, user, sync, size=None)  # 'top' is a sized category
    monkeypatch.setattr(gen, "_download_bytes", lambda url: (b"cut", "image/jpeg"))
    monkeypatch.setattr(
        gen, "generate_from_reference_bytes",
        lambda **kw: GenOutcome("ready", url="https://blob/card.png",
                                content_sha256="aa" * 32, verify_score=0.9),
    )

    gen.run_photo_generation(user.id, db, sync)

    db.refresh(c)
    assert c.generated_image_url == "https://blob/card.png"
    assert c.generation_status == "ready"
    assert c.pipeline_state == "verified_clean"  # NOT ready — tags incomplete
    assert c.person_status == "person_free"


def test_missing_size_defaults_from_facts_at_generation(db, user, monkeypatch):
    db.add(StyleProfile(user_id=user.id, facts={"sizes": {"top": "L"}})); db.commit()
    sync = uuid4(); _run_row(db, user, sync)
    c = _stage(db, user, sync, size=None)
    monkeypatch.setattr(gen, "_download_bytes", lambda url: (b"cut", "image/jpeg"))
    monkeypatch.setattr(
        gen, "generate_from_reference_bytes",
        lambda **kw: GenOutcome("ready", url="https://blob/card.png",
                                content_sha256="aa" * 32, verify_score=0.9),
    )

    gen.run_photo_generation(user.id, db, sync)

    db.refresh(c)
    assert c.size == "L"                      # canonicalize-lite pulled the facts default
    assert c.pipeline_state == "ready"        # tags now complete -> shared invariant passes


def test_stage_time_size_default_from_facts(db, user):
    db.add(StyleProfile(user_id=user.id, facts={"sizes": {"top": "M"}})); db.commit()
    c = _stage_candidate(
        db, user.id, uuid.uuid4(), _G(), "https://blob/cut.jpg", "k-size",
        facts={"sizes": {"top": "M"}},
    )
    db.commit()
    assert c.size == "M"


def test_mark_candidate_ready_rejects_raw_crop_only(db, user):
    """A photo candidate's raw cutout NEVER satisfies the invariant — card required."""
    c = _stage(db, user, uuid4(), person_status="person_free")  # crop, no card
    with pytest.raises(AssertionError):
        readiness.mark_candidate_ready(c)
    # With a verified card the same row passes.
    c.generated_image_url = "https://blob/card.png"
    c.generation_status = "ready"
    readiness.mark_candidate_ready(c)
    assert c.pipeline_state == "ready"


# ===========================================================================
# 4. Re-stage terminal immutability (no ready+person_present resurrection)
# ===========================================================================

def test_restage_restores_person_free_with_its_card(db, user):
    first = _stage_candidate(
        db, user.id, uuid.uuid4(), _G(), "u", "k-restage", on_model=True,
    )
    db.commit()
    first.generation_status = "ready"
    first.generated_image_url = "https://cdn/card.jpg"
    first.pipeline_state = "ready"
    first.person_status = "person_free"
    db.commit()

    again = _stage_candidate(
        db, user.id, uuid.uuid4(), _G(), "u", "k-restage", on_model=True,
    )
    db.commit()
    assert again.id == first.id
    assert again.pipeline_state == "ready"          # terminal never regresses
    assert again.person_status == "person_free"     # the card is the display, not the crop


# ===========================================================================
# 5. Regenerate steering reaches the shared core
# ===========================================================================

def test_regenerate_threads_steering_into_shared_core(db, user, monkeypatch):
    from app.models import ClothingItem

    it = ClothingItem(
        user_id=user.id, name="Crew Tee", category="top", source_type="photo",
        image_url="https://blob/cut.jpg", generation_status="ready",
    )
    db.add(it); db.commit(); db.refresh(it)

    monkeypatch.setattr(gen, "_download_bytes", lambda url: (b"cut", "image/jpeg"))
    seen = {}

    def _fake_core(**kw):
        seen.update(kw)
        return GenOutcome("ready", url="https://blob/card2.png",
                          content_sha256="bb" * 32, verify_score=0.9)

    monkeypatch.setattr(gen, "generate_from_reference_bytes", _fake_core)

    out = gen.run_item_regeneration(
        user.id, db, it.id, reason="logo is on the left chest, not centered",
    )

    assert out.status == "ready" and out.changed
    assert seen["steering"] == "logo is on the left chest, not centered"
    db.refresh(it)
    assert it.image_url == "https://blob/card2.png"
