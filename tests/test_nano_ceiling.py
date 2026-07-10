"""Hard nano ceiling + ladder skip-vs-fail fix + no-double-charge + observability.

The on-cap generator (nano_banana, $0.134) is gated OFF by default at the ONE
dispatch point; a transient verify SKIP no longer advances the ladder to nano or
discards the paid off-cap image; the provider + cost are persisted.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import Base, SessionLocal, engine
from app.gmail_closet.image_verify import VerifyBudget, VerifyVerdict
from app.models import IngestCandidate, IngestRun, User
from app.photo_closet import generation_service as gen
from app.platform.usage import UsageAccumulator
from app.services.image_generation import base as gbase
from app.services.image_generation import generate_core as gc
from app.services.image_generation.base import GenerationBudget, GenerationResult


# ===========================================================================
# 1. The single dispatch gate — nano NEVER instantiated when flag OFF
# ===========================================================================

def test_get_generation_provider_gates_nano_when_off(monkeypatch):
    monkeypatch.setattr(settings, "GENERATION_NANO_FALLBACK_ENABLED", False)
    monkeypatch.setattr(settings, "GENERATION_ENABLED", True)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "k")
    prov = gbase.get_generation_provider("nano_banana")
    assert prov.name == "null"                    # gated -> Null, never NanoBananaProvider


def test_get_generation_provider_allows_nano_when_on(monkeypatch):
    monkeypatch.setattr(settings, "GENERATION_NANO_FALLBACK_ENABLED", True)
    monkeypatch.setattr(settings, "GENERATION_ENABLED", True)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "k")
    prov = gbase.get_generation_provider("nano_banana")
    assert prov.name == "nano_banana"


def test_flux2_still_resolves_regardless_of_nano_flag(monkeypatch):
    monkeypatch.setattr(settings, "GENERATION_NANO_FALLBACK_ENABLED", False)
    monkeypatch.setattr(settings, "GENERATION_ENABLED", True)
    monkeypatch.setattr(settings, "BFL_API_KEY", "k")
    assert gbase.get_generation_provider("flux2_pro").name == "flux2_pro"


def test_t2i_disabled_when_nano_off(monkeypatch):
    monkeypatch.setattr(settings, "GENERATION_NANO_FALLBACK_ENABLED", False)
    called = {"gen": 0}
    import app.services.image_generation.nano_banana as nb
    monkeypatch.setattr(
        nb, "generate_text_to_image",
        lambda *a, **k: called.__setitem__("gen", called["gen"] + 1),
    )
    gb = GenerationBudget(5)
    out = gc.generate_from_text(
        name="Tee", category="top", color="red", brand=None,
        storage_client=object(), user_id=uuid4(),
        gen_budget=gb, verify_budget=VerifyBudget(5), usage=UsageAccumulator(),
    )
    assert out.outcome == "held"
    assert called["gen"] == 0            # nano t2i NEVER invoked
    assert gb.remaining == 5             # no budget consumed on the disabled path


# ===========================================================================
# 2. Ladder: FLUX.2 fails with nano OFF -> no nano, generation fails
# ===========================================================================

def _ref_call(monkeypatch, *, flux_result, verdict, store="https://cdn/card.png",
              nano_result="__fail__"):
    """Drive generate_from_reference_bytes with a spied provider dispatch + verify.

    nano_result default '__fail__' asserts nano is NEVER called; pass an explicit
    value (incl. None) for tests where nano SHOULD be reached (content-fail advance)."""
    def _nano_generate(req):
        if nano_result == "__fail__":
            pytest.fail("nano was invoked despite the OFF ceiling")
        return nano_result

    providers = {
        "flux2_pro": SimpleNamespace(name="flux2_pro", generate=lambda req: flux_result),
        "nano_banana": SimpleNamespace(name="nano_banana", generate=_nano_generate),
    }
    resolved = []

    def _dispatch(name=None):
        resolved.append(name)
        # Honor the real gate: nano off -> Null (returns None), like production.
        if name == "nano_banana" and not settings.GENERATION_NANO_FALLBACK_ENABLED:
            return SimpleNamespace(name="null", generate=lambda req: None)
        return providers[name]

    monkeypatch.setattr(gc, "get_generation_provider", _dispatch)
    monkeypatch.setattr(gc, "verify_generated_image", lambda **k: verdict)
    monkeypatch.setattr(gc, "_store", lambda sc, uid, data, ct: store)
    out = gc.generate_from_reference_bytes(
        reference_bytes=b"crop", reference_content_type="image/png",
        name="Tee", category="top", color="red", brand=None,
        storage_client=object(), user_id=uuid4(),
        gen_budget=GenerationBudget(5), verify_budget=VerifyBudget(5),
        usage=UsageAccumulator(),
    )
    return out, resolved


def _res(provider="flux2_pro", cost=0.045):
    return GenerationResult(
        image_bytes=b"img", content_type="image/png", provider=provider,
        model="m", latency_s=0.1, cost_usd=cost,
    )


def _ok():
    return VerifyVerdict(True, True, True, 0.9, "ok", "m")


def _skip():
    return VerifyVerdict(False, False, False, 0.0, "429", "m", skipped=True)


def _content_fail():
    return VerifyVerdict(False, True, True, 0.2, "person", "m", person_present=True)


def test_flux_error_with_nano_off_fails_no_nano(monkeypatch):
    monkeypatch.setattr(settings, "GENERATION_NANO_FALLBACK_ENABLED", False)
    out, resolved = _ref_call(monkeypatch, flux_result=None, verdict=_ok())
    assert out.outcome in ("held", "budget")     # generation FAILED, no image
    assert out.url is None
    # nano was resolved (the ladder walked to it) but gated to Null -> never generated.
    assert resolved == ["flux2_pro", "nano_banana"]


# ===========================================================================
# 3. verify SKIP does NOT advance; content FAIL does
# ===========================================================================

def test_verify_skip_defers_does_not_advance(monkeypatch):
    monkeypatch.setattr(settings, "GENERATION_NANO_FALLBACK_ENABLED", True)  # even ON:
    out, resolved = _ref_call(monkeypatch, flux_result=_res(), verdict=_skip())
    assert out.outcome == "verify_deferred"      # kept, not advanced
    assert out.url == "https://cdn/card.png"      # flux image STORED (not discarded)
    assert out.provider == "flux2_pro"
    assert resolved == ["flux2_pro"]              # nano NEVER even resolved


def test_verify_content_fail_advances_to_next_rung(monkeypatch):
    monkeypatch.setattr(settings, "GENERATION_NANO_FALLBACK_ENABLED", True)
    # flux content-fails -> advance to nano; nano returns None here -> held.
    out, resolved = _ref_call(
        monkeypatch, flux_result=_res(), verdict=_content_fail(), nano_result=None,
    )
    assert resolved == ["flux2_pro", "nano_banana"]   # genuine fail DID advance
    assert out.outcome == "held"


# ===========================================================================
# 4. No double-charge on verify-skip: photo worker keeps flux, self-heal
#    RE-VERIFIES the stored card (no second generation call)
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
    u = User(email="ceiling@example.com", hashed_password="x", display_name="C")
    db.add(u); db.commit(); db.refresh(u)
    return u


def _cand(db, user, sync, **over):
    fields = dict(
        user_id=user.id, sync_id=sync, source_type="photo", status="pending",
        source_line_key=f"k-{uuid4().hex[:8]}",
        image_url="https://blob/cut.jpg", image_status="user_uploaded",
        name="Crew Tee", category="top", color="red", size="M",
        pipeline_state="image_pending", person_status="person_present",
    )
    fields.update(over)
    c = IngestCandidate(**fields)
    db.add(c); db.commit(); db.refresh(c)
    return c


def test_selfheal_reverifies_deferred_card_no_regeneration(db, user, monkeypatch):
    # A verify_deferred candidate: has a stored card + crop, pending_retry.
    c = _cand(
        db, user, uuid4(), generation_status="pending_retry",
        generated_image_url="https://blob/gen.png",
        generation_provider="flux2_pro", generation_cost_usd=0.045,
    )
    # Re-verify downloads crop + card, verifies -> PASS. NO generation call allowed.
    monkeypatch.setattr(gen, "_download_bytes", lambda url: (b"x", "image/png"))
    monkeypatch.setattr(gen, "verify_generated_image", lambda **k: _ok())
    monkeypatch.setattr(
        gc, "get_generation_provider",
        lambda name=None: pytest.fail("self-heal must NOT generate a deferred card"),
    )

    stats = gen.run_generation_self_heal(user.id, db)

    db.refresh(c)
    assert stats.reverified == 1 and stats.ready == 1
    assert c.generation_status == "ready"
    assert c.generated_image_url == "https://blob/gen.png"   # SAME image — never re-generated
    assert c.person_status == "person_free"


def test_selfheal_deferred_reverify_skip_stays_deferred(db, user, monkeypatch):
    c = _cand(
        db, user, uuid4(), generation_status="pending_retry",
        generated_image_url="https://blob/gen.png",
    )
    monkeypatch.setattr(gen, "_download_bytes", lambda url: (b"x", "image/png"))
    monkeypatch.setattr(gen, "verify_generated_image", lambda **k: _skip())
    monkeypatch.setattr(
        gc, "get_generation_provider",
        lambda name=None: pytest.fail("must not generate"),
    )

    gen.run_generation_self_heal(user.id, db)

    db.refresh(c)
    assert c.generation_status == "pending_retry"        # still deferred
    assert c.generated_image_url == "https://blob/gen.png"
    assert (c.generation_attempts or 0) == 0             # no ceiling burn on a skip


# ===========================================================================
# 5. Observability — provider + cost persisted on a normal ready generation
# ===========================================================================

def test_ready_generation_persists_provider_and_cost(db, user, monkeypatch):
    from tests.test_photo_generation import _providers, _seams, _stage, _verify, _result, _ok as _pg_ok

    sync = uuid4()
    db.add(IngestRun(sync_id=sync, user_id=user.id, status="running", source_type="photo"))
    db.commit()
    c = _stage(db, user, sync)
    _seams(monkeypatch)
    _providers(monkeypatch, {
        "flux2_pro": SimpleNamespace(name="flux2_pro",
                                     generate=lambda req: _result("flux2_pro", cost=0.045)),
        "nano_banana": SimpleNamespace(name="nano_banana", generate=lambda req: None),
    })
    _verify(monkeypatch, lambda **k: _pg_ok())

    gen.run_photo_generation(user.id, db, sync)

    db.refresh(c)
    assert c.generation_status == "ready"
    assert c.generation_provider == "flux2_pro"
    assert float(c.generation_cost_usd) == pytest.approx(0.045)
