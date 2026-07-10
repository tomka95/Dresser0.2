"""Photo-seam Phase 4 — THE confirm chokepoint: one way an item is born.

Gates:
  * confirm_candidates REFUSES any candidate that is not 'ready' — staged photo,
    staged gmail, needs-size without a size edit — via ANY entry point.
  * Manual add routes the SAME seam: candidate + 1-candidate run -> generation
    (t2i or reference) -> verify -> card -> shared readiness -> auto-confirm through
    the chokepoint. Never imageless, never non-compliant.
  * Manual missing-size (no onboarding default): card lands, candidate rests as
    needs-size (reviewable, not blocked-forever), NO item is born until the size is
    supplied.
  * Manual generation exhausted: terminal 'failed', NO item, batch settles.
  * Disarmed manual add is refused up front (503) — no invariant-violating item.
  * PROOF: the ClothingItem constructor/insert exists in exactly ONE production
    path (review_service._upsert_clothing_item) — enumerated by static scan.
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import Base, SessionLocal, engine
from app.gmail_closet import review_service
from app.gmail_closet.review_service import ConfirmError, confirm_candidates, settle_counts
from app.models import IngestCandidate, IngestRun, StyleProfile, User
from app.photo_closet import generation_service as gen
from app.services.closet_service import create_manual_candidate
from app.services.image_generation import generate_core as core
from app.services.image_generation.generate_core import GenOutcome
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
    u = User(email="choke@example.com", hashed_password="x", display_name="C")
    db.add(u); db.commit(); db.refresh(u)
    return u


def _cand(db, user, **over):
    fields = dict(
        user_id=user.id, sync_id=uuid4(), source_type="photo", status="pending",
        source_line_key=f"k-{uuid4().hex[:8]}",
        image_url="https://blob.example/cut.jpg", image_status="user_uploaded",
        name="Crew Tee", category="top", color="red", size="M",
        pipeline_state="staged", person_status="person_free",
    )
    fields.update(over)
    c = IngestCandidate(**fields)
    db.add(c); db.commit(); db.refresh(c)
    return c


def _stub_upsert(monkeypatch):
    """The real upsert is Postgres-only (pg_insert + xmax RETURNING) — stub on SQLite
    and record every birth."""
    births = []

    def _stub(db_, uid, cand, ga_id, facts=None):
        births.append(cand)
        return review_service.WrittenItem(
            clothing_item_id=str(uuid4()), candidate_id=str(cand.id),
            name=cand.name, source_line_key=cand.source_line_key, inserted=True,
        )

    monkeypatch.setattr(review_service, "_upsert_clothing_item", _stub)
    return births


# ===========================================================================
# 1. The chokepoint refuses every non-'ready' candidate
# ===========================================================================

def test_confirm_refuses_staged_photo_candidate(db, user, monkeypatch):
    births = _stub_upsert(monkeypatch)
    c = _cand(db, user, pipeline_state="staged")
    with pytest.raises(ConfirmError, match="not ready"):
        confirm_candidates(db, user.id, accepted=[str(c.id)])
    assert births == []


def test_confirm_refuses_staged_gmail_candidate(db, user, monkeypatch):
    births = _stub_upsert(monkeypatch)
    c = _cand(db, user, source_type="gmail", image_status="pending",
              image_url=None, person_status="unknown", pipeline_state="staged")
    with pytest.raises(ConfirmError, match="not ready"):
        confirm_candidates(db, user.id, accepted=[str(c.id)])
    assert births == []


def test_confirm_accepts_verified_clean_without_size(db, user, monkeypatch):
    # Fix 1: SIZE OPTIONAL — a verified_clean card with no size is now ready-eligible;
    # confirm completes it through the shared ready-writer and the item is born. No
    # more "add a size to finish it" dead-end.
    births = _stub_upsert(monkeypatch)
    c = _cand(db, user, size=None, pipeline_state="verified_clean",
              generation_status="ready", generated_image_url="https://cdn/card.png")
    result = confirm_candidates(db, user.id, accepted=[str(c.id)])
    db.refresh(c)
    assert c.pipeline_state == "ready" and c.status == "accepted"
    assert c.size is None                            # size never required
    assert len(births) == 1 and result.accepted_count == 1


def test_confirm_accepts_ready_candidate(db, user, monkeypatch):
    births = _stub_upsert(monkeypatch)
    c = _cand(db, user, pipeline_state="ready", generation_status="ready",
              generated_image_url="https://cdn/card.png")
    confirm_candidates(db, user.id, accepted=[str(c.id)])
    assert len(births) == 1 and births[0].id == c.id


# ===========================================================================
# 2/3. Manual add — through the seam, born only via the chokepoint
# ===========================================================================

def _run_manual(db, user, monkeypatch, *, outcome=None, facts=None):
    """Stage a manual candidate + run the manual generation pass with a faked core."""
    if facts is not None:
        db.add(StyleProfile(user_id=user.id, facts=facts)); db.commit()
    run, cand = create_manual_candidate(
        db, user.id, name="Navy Crewneck Sweater", category="top", brand=None,
        color="navy",
    )
    monkeypatch.setattr(
        core, "generate_from_text",
        lambda **kw: outcome
        or GenOutcome("ready", url="https://cdn/manual-card.png",
                      content_sha256="dd" * 32, verify_score=0.9),
    )
    monkeypatch.setattr(gen, "_storage_from_env", lambda: object())
    # Enrichment runs inline post-birth — no-op it (own network/session).
    import app.services.enrichment as enrichment
    monkeypatch.setattr(enrichment, "enrich_items_background", lambda *a, **k: None)
    stats = gen.run_manual_generation(user.id, db, run.sync_id)
    db.refresh(cand)
    return run, cand, stats


def test_manual_add_generates_card_and_is_born_via_chokepoint(db, user, monkeypatch):
    births = _stub_upsert(monkeypatch)
    run, cand, stats = _run_manual(
        db, user, monkeypatch, facts={"sizes": {"top": "L"}},
    )

    assert stats.ready == 1
    assert cand.generated_image_url == "https://cdn/manual-card.png"
    assert cand.generation_status == "ready"
    assert cand.pipeline_state == "ready" and cand.person_status == "person_free"
    assert cand.size == "L"                     # onboarding default, as everywhere
    assert cand.status == "accepted"            # auto-confirmed THROUGH the chokepoint
    assert len(births) == 1 and births[0].id == cand.id
    db.refresh(run)
    assert run.status == "completed"
    assert settle_counts(db, user.id, str(run.sync_id)).settled


def test_manual_missing_size_still_born_size_optional(db, user, monkeypatch):
    # Fix 1: a manual add with no derivable size is NOT held — it reaches 'ready' and
    # auto-confirms into the closet (size optional). The 'add size' flag rides along
    # as a soft nicety on the resulting card.
    births = _stub_upsert(monkeypatch)
    run, cand, stats = _run_manual(db, user, monkeypatch)  # no facts -> no default

    assert cand.generated_image_url == "https://cdn/manual-card.png"
    assert cand.pipeline_state == "ready"            # size optional -> ready
    assert cand.size is None
    assert cand.status == "accepted"                 # auto-confirmed -> item born
    assert len(births) == 1
    from app.services.readiness import needs_size
    assert needs_size(cand) is True                  # soft affordance still true


def test_manual_generation_exhausted_is_terminal_failed_no_item(db, user, monkeypatch):
    births = _stub_upsert(monkeypatch)
    monkeypatch.setattr(settings, "GENERATION_MAX_ATTEMPTS", 2)
    run, cand, stats = _run_manual(
        db, user, monkeypatch, outcome=GenOutcome("held"),
        facts={"sizes": {"top": "L"}},
    )

    assert cand.generation_status == "failed"
    assert cand.pipeline_state == "failed"
    assert cand.generation_attempts == 2      # inline retries to the ceiling
    assert births == []                       # no item, ever
    assert settle_counts(db, user.id, str(run.sync_id)).settled
    db.refresh(run)
    assert run.status == "completed"


def test_manual_route_refuses_when_generation_unavailable(db, user, monkeypatch):
    monkeypatch.setattr(gen, "generation_armed", lambda: False)
    client = TestClient(app)
    token = mint_supabase_token(sub=str(user.id))
    resp = client.post(
        "/closet", json={"name": "Navy Sweater"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 503


def test_manual_route_stages_candidate_and_returns_202(db, user, monkeypatch):
    monkeypatch.setattr(gen, "generation_armed", lambda: True)
    monkeypatch.setattr(gen, "_storage_from_env", lambda: object())
    monkeypatch.setattr(gen, "manual_generate_background", lambda *a: None)
    client = TestClient(app)
    token = mint_supabase_token(sub=str(user.id))
    resp = client.post(
        "/closet", json={"name": "Navy Sweater", "category": "top", "color": "navy"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "tailoring"
    cand = db.query(IngestCandidate).filter(IngestCandidate.user_id == user.id).one()
    assert str(cand.id) == body["candidateId"]
    assert cand.source_type == "manual" and cand.pipeline_state == "staged"
    assert cand.person_status == "unknown"    # fail-closed until the card lands
    run = db.query(IngestRun).filter(IngestRun.user_id == user.id).one()
    assert run.source_type == "manual" and str(run.sync_id) == body["syncId"]


# ===========================================================================
# 5. PROOF — exactly one production birth path for clothing_items
# ===========================================================================

def test_one_and_only_one_item_birth_path():
    """Static enumeration: the ClothingItem constructor / insert target appears in
    production code ONLY inside review_service (the confirm upsert) and the model
    definition itself. Former paths, now removed/routed:
      * closet_service.create_closet_item (manual direct insert) -> replaced by
        create_manual_candidate + the seam + auto-confirm through the chokepoint.
      * outfit_db_service.save_outfit_results_to_db (legacy) -> deleted in the
        closet-intake overhaul.
    """
    app_dir = Path(__file__).resolve().parent.parent / "app"
    allowed = {
        app_dir / "models" / "closet.py",                 # the model class definition
        app_dir / "gmail_closet" / "review_service.py",   # THE chokepoint upsert
    }
    pattern = re.compile(r"(?:pg_insert|insert)\(\s*ClothingItem\s*\)|ClothingItem\(")
    offenders = []
    for path in app_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for m in pattern.finditer(text):
            # The class definition line ("class ClothingItem(Base)") lives in models.
            if path in allowed:
                continue
            offenders.append(f"{path.relative_to(app_dir.parent)}: {m.group(0)}")
    assert offenders == [], (
        "clothing_items must be born ONLY via review_service._upsert_clothing_item; "
        f"found other constructor/insert sites: {offenders}"
    )
