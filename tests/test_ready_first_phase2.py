"""Ready-first Phase 2: background person-verification + generation-to-completion.

Contract under test:
  * Every email image gets an AFFIRMATIVE person check; the verdict is persisted
    (person_free / person_present) — never left 'unknown' once checked.
  * person_present (or unknown) can NEVER surface: the image is replaced by a verified
    person-free generated card or the candidate stays masked / goes terminal 'failed'.
  * pipeline_state is driven to 'ready' ⟺ person_free + stored verified image +
    complete tags (size defaulted from onboarding facts); retry-exhaustion -> 'failed'.
  * Generation runs in the BACKGROUND fill pass — never at confirm.
  * Idempotent/crash-safe: terminal candidates are never re-selected; the shared
    product-image cache prevents double-charging for the same product.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

import app.gmail_closet.image_fill_service as F
from app.core.config import settings
from app.db import Base, SessionLocal, engine
from app.gmail_closet.image_verify import VerifyVerdict
from app.models import IngestCandidate, User
from app.services.image_generation.base import GenerationBudget
from app.gmail_closet.image_verify import VerifyBudget
from app.gmail_closet.image_guard import FetchBudget


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
    u = User(email=f"p2-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


def _cand(db, user, *, image="https://cdn/raw.jpg", person="unknown", state="staged",
          size=None, category="top", gen_attempts=0, image_status="resolved",
          status="pending"):
    c = IngestCandidate(
        user_id=user.id, sync_id=uuid.uuid4(), source_line_key=uuid.uuid4().hex,
        name="Define Jacket", brand="lululemon", category=category, size=size,
        status=status, source_type="gmail", image_url=image,
        image_status=(image_status if image else "pending"),
        person_status=person, pipeline_state=state, generation_attempts=gen_attempts,
    )
    db.add(c); db.commit(); db.refresh(c)
    return c


def _verdict(matches=True, person=False, skipped=False):
    return VerifyVerdict(
        matches=matches, garment_ok=matches, color_ok=matches, score=0.9 if matches else 0.1,
        reason="t", model="m", person_present=person, skipped=skipped,
    )


def _budgets():
    return dict(
        gen_budget=GenerationBudget(50),
        verify_budget=VerifyBudget(200),
        fetch_budget=FetchBudget(100),
    )


def _fetched(url="u"):
    return SimpleNamespace(content=b"imgbytes", content_type="image/jpeg", suffix=".jpg")


def _patch_fetch(monkeypatch, ok=True):
    if ok:
        monkeypatch.setattr(F, "guarded_fetch", lambda *a, **k: _fetched())
    else:
        def boom(*a, **k): raise RuntimeError("net down")
        monkeypatch.setattr(F, "guarded_fetch", boom)


def _patch_gen(monkeypatch, outcome="ready"):
    """Patch generate_core seams used (lazily) by _reconcile_person."""
    import app.services.image_generation.generate_core as gc
    calls = {"n": 0}

    def fake_gen(**kw):
        calls["n"] += 1
        if outcome == "ready":
            return gc.GenOutcome("ready", url="https://cdn/clean-card.jpg",
                                 content_sha256="a" * 64, verify_score=0.9, cost_usd=0.045)
        return gc.GenOutcome(outcome)

    monkeypatch.setattr(gc, "generate_from_reference_bytes", fake_gen)
    monkeypatch.setattr(gc, "generation_armed", lambda: True)
    monkeypatch.setattr(F, "promote_verified", lambda **kw: None)
    return calls


def _reconcile(db, cands, monkeypatch, verdict, gen_outcome="ready", fetch_ok=True):
    _patch_fetch(monkeypatch, ok=fetch_ok)
    calls = _patch_gen(monkeypatch, outcome=gen_outcome)
    monkeypatch.setattr(F, "verify_image", lambda **kw: verdict)
    stats = F.ImageFillStats(user_id=cands[0].user_id)
    F._reconcile_person(
        db, cands, user_id=cands[0].user_id, http=object(), storage_client=object(),
        usage=None, stats=stats, **_budgets(),
    )
    return stats, calls


# ===========================================================================
# 1. Email on-model image -> generated -> verified -> person_free -> ready
# ===========================================================================

def test_on_model_email_image_generated_to_ready(db, user, monkeypatch):
    c = _cand(db, user, size="M")   # image present, person unknown (the live-64 shape)
    stats, calls = _reconcile(db, [c], monkeypatch, _verdict(person=True))

    assert calls["n"] == 1                               # routed through generation
    assert c.image_url == "https://cdn/clean-card.jpg"   # card REPLACED the raw image
    assert c.person_status == "person_free"
    F._stamp_final(c, stats)
    assert c.pipeline_state == "ready"
    # The raw person image is gone from the row entirely — nothing can display it.


def test_person_present_recorded_even_when_generation_misses(db, user, monkeypatch):
    c = _cand(db, user)
    stats, calls = _reconcile(db, [c], monkeypatch, _verdict(person=True), gen_outcome="held")

    assert c.person_status == "person_present"           # NEVER unknown once checked
    assert c.image_url == "https://cdn/raw.jpg"          # kept only as gen reference
    assert c.generation_attempts == 1                    # real miss burns one attempt
    F._stamp_final(c, stats)
    assert c.pipeline_state != "ready"                   # masked, not ready


# ===========================================================================
# 2. person_free product shot -> ready WITHOUT needless regeneration
# ===========================================================================

def test_person_free_email_shot_ready_without_regen(db, user, monkeypatch):
    c = _cand(db, user, size="M")
    stats, calls = _reconcile(db, [c], monkeypatch, _verdict(person=False))

    assert calls["n"] == 0                               # no generation call ($0)
    assert c.person_status == "person_free"
    assert c.image_url == "https://cdn/raw.jpg"          # original clean shot kept
    F._stamp_final(c, stats)
    assert c.pipeline_state == "ready"


# ===========================================================================
# 3. Detection error -> stays unknown -> masked, retried later
# ===========================================================================

def test_verify_skipped_stays_unknown_and_masked(db, user, monkeypatch):
    c = _cand(db, user)
    stats, calls = _reconcile(db, [c], monkeypatch, _verdict(skipped=True, matches=False))

    assert c.person_status == "unknown"                  # no affirmative verdict
    assert calls["n"] == 0
    F._stamp_final(c, stats)
    assert c.pipeline_state == "image_pending"           # residue: retried next run
    # fail-closed display: unknown is masked (Phase 1 mask asserted there)


def test_fetch_error_stays_unknown(db, user, monkeypatch):
    c = _cand(db, user)
    stats, calls = _reconcile(db, [c], monkeypatch, _verdict(), fetch_ok=False)
    assert c.person_status == "unknown"
    assert c.pipeline_state != "ready"


def test_wrong_image_cleared_back_to_pending(db, user, monkeypatch):
    c = _cand(db, user)
    stats, calls = _reconcile(db, [c], monkeypatch, _verdict(matches=False, skipped=False))
    assert c.image_url is None                           # wrong product image dropped
    assert c.image_status == "pending"                   # resolver re-resolves later


# ===========================================================================
# 4. Generation is BACKGROUND-only: confirm makes no generation call
# ===========================================================================

def test_confirm_makes_no_generation_call(db, user, monkeypatch):
    import app.services.image_generation.generate_core as gc
    from app.gmail_closet import review_service as RS

    def boom(**kw): raise AssertionError("confirm must never generate")
    monkeypatch.setattr(gc, "generate_from_reference_bytes", boom)
    monkeypatch.setattr(gc, "generate_from_text", boom)

    c = _cand(db, user, person="person_free", state="ready")
    # SQLite can't run the Postgres ON CONFLICT upsert — patch the write itself and
    # assert the confirm path completes WITHOUT touching any generation seam.
    monkeypatch.setattr(
        RS, "_upsert_clothing_item",
        lambda *a, **k: RS.WrittenItem(
            clothing_item_id=str(uuid.uuid4()), candidate_id="c", name="Define Jacket",
            source_line_key="k", inserted=True,
        ),
    )
    result = RS.confirm_candidates(db, user.id, accepted=[str(c.id)], rejected=[])
    assert len(result.written) == 1                      # confirmed; zero generation


# ===========================================================================
# 5. Retry-exhausted -> terminal 'failed', never ready, excluded from deck
# ===========================================================================

def test_retry_exhausted_person_image_goes_failed(db, user, monkeypatch):
    from app.gmail_closet.review_service import list_pending_candidates
    monkeypatch.setattr(settings, "GENERATION_MAX_ATTEMPTS", 2)
    c = _cand(db, user, person="person_present", gen_attempts=2, state="image_pending")
    stats = F.ImageFillStats(user_id=user.id)
    F._stamp_final(c, stats)
    db.commit()
    assert c.pipeline_state == "failed"
    assert stats.failed == 1
    assert list_pending_candidates(db, user.id) == []    # excluded from the deck


def test_placeholder_terminal_goes_failed(db, user):
    c = _cand(db, user, image=None, state="image_pending")
    c.image_status = "placeholder"
    stats = F.ImageFillStats(user_id=user.id)
    F._stamp_final(c, stats)
    assert c.pipeline_state == "failed"


# ===========================================================================
# 6. The invariant: ready ⟺ person_free + stored verified image + tags
# ===========================================================================

def test_ready_invariant_rejects_non_person_free(db, user):
    c = _cand(db, user, person="person_present")
    with pytest.raises(AssertionError):
        F.mark_candidate_ready(c)


def test_ready_invariant_rejects_missing_image(db, user):
    c = _cand(db, user, image=None, person="person_free")
    with pytest.raises(AssertionError):
        F.mark_candidate_ready(c)


def test_ready_invariant_rejects_unknown(db, user):
    c = _cand(db, user, person="unknown")
    with pytest.raises(AssertionError):
        F.mark_candidate_ready(c)


def test_ready_invariant_accepts_complete_candidate(db, user):
    c = _cand(db, user, person="person_free", size="M")
    F.mark_candidate_ready(c)
    assert c.pipeline_state == "ready"


# ===========================================================================
# 7. Canonicalize-lite: size defaulted from onboarding facts
# ===========================================================================

def test_size_defaulted_from_facts(db, user):
    c = _cand(db, user, size=None, category="top")
    F._apply_canonicalized(c, {"sizes": {"top": "M"}})
    assert c.size == "M"
    assert c.pipeline_state == "canonicalized"


def test_sized_category_without_default_blocks_ready(db, user):
    c = _cand(db, user, size=None, category="top", person="person_free")
    F._apply_canonicalized(c, {})                        # no facts -> no default
    stats = F.ImageFillStats(user_id=user.id)
    F._stamp_final(c, stats)
    assert c.pipeline_state == "verified_clean"          # image fine; tags incomplete


def test_sizeless_category_reaches_ready_without_size(db, user):
    c = _cand(db, user, size=None, category="accessories", person="person_free")
    F._apply_canonicalized(c, {})
    stats = F.ImageFillStats(user_id=user.id)
    F._stamp_final(c, stats)
    assert c.pipeline_state == "ready"                   # accessories have no size key


# ===========================================================================
# 8. Idempotency / crash-resume / cache double-charge
# ===========================================================================

def test_terminal_candidates_not_reselected(db, user, monkeypatch):
    ready = _cand(db, user, person="person_free", state="ready")
    failed = _cand(db, user, state="failed")
    live = _cand(db, user, state="image_pending")

    rows = (
        db.query(IngestCandidate)
        .filter(
            IngestCandidate.user_id == user.id,
            IngestCandidate.status == "pending",
            IngestCandidate.source_type == "gmail",
            IngestCandidate.pipeline_state.notin_(F._TERMINAL_STATES),
        )
        .all()
    )
    assert [r.id for r in rows] == [live.id]             # crash-resume: only residue


def test_advance_never_regresses_or_leaves_terminal(db, user):
    c = _cand(db, user, state="verified_clean")
    F._advance(c, "image_pending")
    assert c.pipeline_state == "verified_clean"          # no regression
    c.pipeline_state = "ready"
    F._advance(c, "canonicalized")
    assert c.pipeline_state == "ready"                   # terminal untouched
    F._apply_canonicalized(c, {"sizes": {"top": "M"}})
    assert c.pipeline_state == "ready"


def test_t2i_promotes_to_cache_preventing_double_charge(monkeypatch):
    import app.services.image_generation.generate_core as gc
    promoted = {}
    monkeypatch.setattr(
        F, "promote_verified", lambda **kw: promoted.update(kw)
    )
    monkeypatch.setattr(
        gc, "generate_from_text",
        lambda **kw: gc.GenOutcome("ready", url="https://cdn/t2i.jpg",
                                   content_sha256="b" * 64, verify_score=0.8),
    )
    monkeypatch.setattr(gc, "generation_armed", lambda: True)
    t = SimpleNamespace(name="Define Jacket", brand="lululemon", color="black",
                        category="outerwear")
    url = F._maybe_t2i(t, object(), uuid.uuid4(), GenerationBudget(5), VerifyBudget(5), None)
    assert url == "https://cdn/t2i.jpg"
    # promoted into the shared verified cache -> the cache-first pass serves the same
    # product next time at ~0 cost (no second generation call for identical items).
    assert promoted["source_tier"] == "generated"
    assert promoted["image_url"] == "https://cdn/t2i.jpg"


# ===========================================================================
# 9. Resolver fail-closed: a person image with no gen budget is REJECTED
# ===========================================================================

def test_resolver_rejects_person_image_without_gen_budget(monkeypatch):
    import app.gmail_closet.image_resolver.resolve as R

    monkeypatch.setattr(R, "verify_image", lambda **kw: _verdict(person=True))
    monkeypatch.setattr(R.settings, "GMAIL_VERIFY_ENABLED", True)
    monkeypatch.setattr(R, "extract_inline_images", lambda *a, **k: ({}, []))
    monkeypatch.setattr(R, "extract_html", lambda p: "")

    stored = {"n": 0}

    class _Ref:
        inline_cids = ["cid1"]
        remote_imgs = []
        product_links = []

    monkeypatch.setattr(R, "associate", lambda h, items: [_Ref()])
    # one inline image so the single-item fallback path runs _accept
    img = SimpleNamespace(raw=b"x", suffix=".jpg", content_type="image/jpeg")
    monkeypatch.setattr(R, "extract_inline_images", lambda *a, **k: ({}, [img]))
    monkeypatch.setattr(R, "_upload", lambda *a, **k: stored.update(n=stored["n"] + 1))

    out = R.resolve_item_images(
        payload={}, items=[R.ResolverItem(name="Jacket", category="outerwear")],
        client=None, token="t", msg_id="m", storage_client=None,
        cache=R.ResolvedImageCache(), user_id=uuid.uuid4(),
        tiers=frozenset({"inline"}),
        gen_budget=None,                                  # foreground: no generation
    )
    assert out[0].tier == "none"                          # REJECTED, not committed
    assert out[0].stored_url is None
    assert stored["n"] == 0                               # never uploaded/stored


def test_resolver_marks_person_free_on_clean_accept(monkeypatch):
    import app.gmail_closet.image_resolver.resolve as R
    from app.gmail_closet.image_resolver._storage import _Stored

    monkeypatch.setattr(R, "verify_image", lambda **kw: _verdict(person=False))
    monkeypatch.setattr(R.settings, "GMAIL_VERIFY_ENABLED", True)
    monkeypatch.setattr(R, "extract_html", lambda p: "")
    img = SimpleNamespace(raw=b"x", suffix=".jpg", content_type="image/jpeg")
    monkeypatch.setattr(R, "extract_inline_images", lambda *a, **k: ({}, [img]))

    class _Ref:
        inline_cids = []
        remote_imgs = []
        product_links = []

    monkeypatch.setattr(R, "associate", lambda h, items: [_Ref()])
    monkeypatch.setattr(R, "_upload", lambda *a, **k: _Stored(url="https://cdn/ok.jpg", sha="s"))
    monkeypatch.setattr(R, "promote_verified", lambda **kw: None)

    out = R.resolve_item_images(
        payload={}, items=[R.ResolverItem(name="Jacket", category="outerwear")],
        client=None, token="t", msg_id="m", storage_client=None,
        cache=R.ResolvedImageCache(), user_id=uuid.uuid4(),
        tiers=frozenset({"inline"}),
    )
    assert out[0].stored_url == "https://cdn/ok.jpg"
    assert out[0].person == "person_free"                 # affirmative verdict surfaced
