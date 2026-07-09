"""Photo-seam Phase 2 — ONE invariant prompt + verify v2 hard gates.

Gates asserted here:
  * INVARIANT_BLOCK is ONE definition embedded by BOTH generation entry points
    (reference prompt + t2i prompt) and every ladder provider imports the one
    prompt seam — no per-pipeline drift.
  * verify_generated_image hard-FAILS a candidate with: a person, an extra
    garment/object, a non-off-white background, or closeup/tight-crop framing —
    and PASSES a clean single-item off-white catalog card.
  * generate_from_text enforces the same invariant gates on its (single-image
    verified) output.
  * On the photo worker: an invariant-failing candidate is never stored, never
    'ready', person_status is NOT flipped (person_free only on a full pass), and
    after the attempt ceiling it goes terminal 'failed'.
  * The conftest key-guard: tests never see real provider keys.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import Base, SessionLocal, engine
from app.gmail_closet import image_verify as iv
from app.gmail_closet.image_verify import VerifyBudget, VerifyVerdict, _VerdictSchema
from app.models import IngestCandidate, IngestRun, User
from app.platform import ai_provider as ai
from app.platform.usage import UsageAccumulator
from app.photo_closet import generation_service as gen
from app.services.image_generation import (
    flux2_pro,
    flux_kontext,
    generate_core as gc,
    nano_banana,
    prompt as prompt_mod,
    seedream,
)
from app.services.image_generation.base import GenerationBudget, GenerationRequest, GenerationResult


# --------------------------------------------------------------------------- fakes

class _Resp:
    def __init__(self, verdict: _VerdictSchema):
        self.parsed = verdict
        self.text = None


class _Provider:
    def __init__(self, verdict: _VerdictSchema):
        self._verdict = verdict

    def generate_structured(self, **kw):
        return _Resp(self._verdict)


def _enable_verify(monkeypatch):
    monkeypatch.setattr(settings, "GMAIL_VERIFY_ENABLED", True)
    monkeypatch.setattr(settings, "GMAIL_VERIFY_SCORE_THRESHOLD", 0.5)


def _patch_ai(monkeypatch, verdict: _VerdictSchema):
    monkeypatch.setattr(ai, "get_ai_provider", lambda: _Provider(verdict))


def _clean_card(**over) -> _VerdictSchema:
    """A model verdict for a perfect card: single item, off-white, catalog framing."""
    fields = dict(
        garment_ok=True, color_ok=True, pattern_ok=True, logo_text_ok=True,
        logo_present_parity=True, logo_count_ok=True, logo_placement_ok=True,
        logo_identity_ok=True, person_present=False,
        extra_items_present=False, background_offwhite_ok=True, framing_ok=True,
        matches=True, score=0.9, reason="ok",
    )
    fields.update(over)
    return _VerdictSchema(**fields)


def _pair_verify(**kw) -> VerifyVerdict:
    return iv.verify_generated_image(
        reference_bytes=b"ref", reference_content_type="image/jpeg",
        candidate_bytes=b"cand", candidate_content_type="image/png",
        category="top", color="red", pattern=None, name="Red Tee", **kw,
    )


# ===========================================================================
# 1. ONE shared invariant prompt
# ===========================================================================

def test_invariant_block_is_in_both_entry_points():
    req = GenerationRequest(
        image_bytes=b"x", content_type="image/jpeg",
        name="Red Tee", category="top", color="red", pattern=None, brand=None,
    )
    ref_prompt = prompt_mod.build_generation_prompt(req)
    t2i_prompt = prompt_mod.build_t2i_prompt("Red Tee", "top", "red", None)

    assert prompt_mod.INVARIANT_BLOCK in ref_prompt
    assert prompt_mod.INVARIANT_BLOCK in t2i_prompt
    # nano's hardened variant keeps the block too (it only APPENDS the logo guard).
    assert prompt_mod.INVARIANT_BLOCK in prompt_mod.build_nano_generation_prompt(req)
    # The three rules are explicit in the ONE block.
    for phrase in ("SINGLE ITEM ONLY", "OFF-WHITE BACKGROUND", "CATALOG FRAMING"):
        assert phrase in prompt_mod.INVARIANT_BLOCK


def test_every_provider_and_core_share_the_one_prompt_definition():
    # Ladder providers build from the SAME function objects — no forked copies.
    assert flux2_pro.build_generation_prompt is prompt_mod.build_generation_prompt
    assert flux_kontext.build_generation_prompt is prompt_mod.build_generation_prompt
    assert seedream.build_generation_prompt is prompt_mod.build_generation_prompt
    assert nano_banana.build_nano_generation_prompt is prompt_mod.build_nano_generation_prompt
    # generate_core re-exports the ONE t2i builder (moved to the prompt seam).
    assert gc.build_t2i_prompt is prompt_mod.build_t2i_prompt


# ===========================================================================
# 2. Verify v2 — the invariant as HARD gates on the generated (pair) pass
# ===========================================================================

def test_clean_single_item_offwhite_proportional_passes(monkeypatch):
    _enable_verify(monkeypatch)
    _patch_ai(monkeypatch, _clean_card())
    v = _pair_verify()
    assert v.matches is True
    assert v.person_present is False and v.extra_items_present is False
    assert v.background_offwhite_ok is True and v.framing_ok is True


def test_person_in_candidate_fails(monkeypatch):
    _enable_verify(monkeypatch)
    _patch_ai(monkeypatch, _clean_card(person_present=True))
    v = _pair_verify()
    assert v.matches is False and v.person_present is True


def test_extra_garment_or_object_fails(monkeypatch):
    _enable_verify(monkeypatch)
    _patch_ai(monkeypatch, _clean_card(extra_items_present=True))
    v = _pair_verify()
    assert v.matches is False and v.extra_items_present is True


def test_non_offwhite_background_fails(monkeypatch):
    _enable_verify(monkeypatch)
    _patch_ai(monkeypatch, _clean_card(background_offwhite_ok=False))
    v = _pair_verify()
    assert v.matches is False and v.background_offwhite_ok is False


def test_closeup_or_tight_crop_framing_fails(monkeypatch):
    _enable_verify(monkeypatch)
    _patch_ai(monkeypatch, _clean_card(framing_ok=False))
    v = _pair_verify()
    assert v.matches is False and v.framing_ok is False


def test_email_single_image_pass_surfaces_but_does_not_gate(monkeypatch):
    """Real retailer images are NOT generated cards: the single-image pass reports the
    invariant flags but matches stays garment+color — email tier acceptance unchanged."""
    _enable_verify(monkeypatch)
    _patch_ai(monkeypatch, _clean_card(background_offwhite_ok=False, framing_ok=False))
    v = iv.verify_image(
        image_bytes=b"img", content_type="image/jpeg",
        category="top", color="red", name="Red Tee",
    )
    assert v.matches is True  # garment+color gate only
    assert v.background_offwhite_ok is False and v.framing_ok is False


# ===========================================================================
# 3. t2i (generate_from_text) enforces the same hard gates
# ===========================================================================

def _t2i(monkeypatch, verdict: VerifyVerdict):
    monkeypatch.setattr(
        nano_banana, "generate_text_to_image",
        lambda p: GenerationResult(
            image_bytes=b"t2i", content_type="image/png", provider="nano_banana",
            model="m", latency_s=0.1, cost_usd=0.13,
        ),
    )
    monkeypatch.setattr(gc, "verify_image", lambda **k: verdict)
    monkeypatch.setattr(gc, "_store", lambda sc, uid, data, ct: "https://cdn/t2i.png")
    return gc.generate_from_text(
        name="Red Tee", category="top", color="red", brand=None,
        storage_client=object(), user_id=uuid4(),
        gen_budget=GenerationBudget(5), verify_budget=VerifyBudget(5),
        usage=UsageAccumulator(),
    )


def test_t2i_holds_on_each_invariant_violation(monkeypatch):
    base = dict(matches=True, garment_ok=True, color_ok=True, score=0.9,
                reason="ok", model="m")
    for bad in (
        dict(person_present=True),
        dict(extra_items_present=True),
        dict(background_offwhite_ok=False),
        dict(framing_ok=False),
    ):
        out = _t2i(monkeypatch, VerifyVerdict(**{**base, **bad}))
        assert out.outcome == "held", f"should hold on {bad}"


def test_t2i_ready_on_full_pass(monkeypatch):
    out = _t2i(monkeypatch, VerifyVerdict(
        matches=True, garment_ok=True, color_ok=True, score=0.9, reason="ok", model="m",
    ))
    assert out.outcome == "ready" and out.url == "https://cdn/t2i.png"


# ===========================================================================
# 4. Photo worker: invariant fail -> never stored, person_status untouched,
#    terminal 'failed' after the attempt ceiling — not 'ready'
# ===========================================================================

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
    u = User(email="inv@example.com", hashed_password="x", display_name="I")
    db.add(u); db.commit(); db.refresh(u)
    return u


def test_invariant_fail_never_ready_and_person_status_untouched(db, user, monkeypatch):
    _enable_verify(monkeypatch)
    monkeypatch.setattr(settings, "GENERATION_MAX_ATTEMPTS", 1)  # terminal on first miss
    sync = uuid4()
    db.add(IngestRun(sync_id=sync, user_id=user.id, status="running", source_type="photo"))
    db.commit()
    c = IngestCandidate(
        user_id=user.id, sync_id=sync, source_type="photo", status="pending",
        image_url="https://blob/cut.jpg", image_status="user_uploaded",
        name="Red Tee", category="top", color="red", size="M",
        on_model=True, person_status="person_present", pipeline_state="staged",
    )
    db.add(c); db.commit(); db.refresh(c)

    monkeypatch.setattr(gen, "_download_bytes", lambda url: (b"cut", "image/jpeg"))
    # Real core + real verify decision path; the MODEL flags an extra garment in frame.
    monkeypatch.setattr(
        gc, "get_generation_provider",
        lambda name=None: SimpleNamespace(generate=lambda req: GenerationResult(
            image_bytes=b"gen", content_type="image/png", provider=str(name),
            model="m", latency_s=0.1, cost_usd=0.045,
        )),
    )
    _patch_ai(monkeypatch, _clean_card(extra_items_present=True))
    monkeypatch.setattr(
        gc, "_store", lambda *a, **k: pytest.fail("invariant-violating card must not be stored")
    )

    stats = gen.run_photo_generation(user.id, db, sync)

    db.refresh(c)
    assert stats.ready == 0
    assert c.generated_image_url is None
    assert c.generation_status == "failed"        # ceiling=1 -> terminal, not re-billed
    assert c.pipeline_state == "failed"           # terminal — NOT 'ready'
    assert c.person_status == "person_present"    # person_free ONLY on a full pass


# ===========================================================================
# 5. Key-guard — tests never see real provider keys
# ===========================================================================

def test_key_guard_replaces_real_keys():
    assert settings.GEMINI_API_KEY == "test-key-not-real"
    assert settings.BFL_API_KEY == "test-key-not-real"
    assert settings.SUPABASE_S3_SECRET_KEY == "test-key-not-real"
