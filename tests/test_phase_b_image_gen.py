"""Phase B (Fix 4): person backstop in verify + the bytes-native generate core.

Covers the structural "no person in the closet" guarantees without any network:
  * verify_generated_image FAILS a candidate with a person (unconditional), passes a
    person-free one; verify_image SURFACES person_present (on_model) but does not itself
    fail on it (the email path routes on that flag).
  * generate_core.generate_from_reference_bytes / generate_from_text store ONLY a verified,
    person-free image — a person (or any verify miss) yields 'held', never a stored image
    (so the fallback ladder can never store a person).
  * the email on-model router returns a generated result on success, None on a miss (so the
    resolver rejects the on-model original and falls through — never storing it).
"""
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.gmail_closet import image_verify as iv
from app.gmail_closet.image_verify import VerifyBudget, VerifyVerdict, _VerdictSchema
from app.services.image_generation import generate_core as gc
from app.services.image_generation.base import GenerationBudget, GenerationResult
from app.platform.usage import UsageAccumulator


class _Resp:
    def __init__(self, verdict: _VerdictSchema):
        self.parsed = verdict
        self.text = None


class _Provider:
    def __init__(self, verdict: _VerdictSchema):
        self._v = verdict

    def generate_structured(self, **kw):
        return _Resp(self._v)


def _enable_verify(monkeypatch):
    monkeypatch.setattr(settings, "GMAIL_VERIFY_ENABLED", True)
    monkeypatch.setattr(settings, "GMAIL_VERIFY_SCORE_THRESHOLD", 0.5)


def _patch_provider(monkeypatch, verdict: _VerdictSchema):
    import app.platform.ai_provider as ai

    monkeypatch.setattr(ai, "get_ai_provider", lambda: _Provider(verdict))


def _full_ok(**over):
    base = dict(
        garment_ok=True, color_ok=True, pattern_ok=True, logo_text_ok=True,
        logo_present_parity=True, logo_count_ok=True, logo_placement_ok=True,
        logo_identity_ok=True, person_present=False, matches=True, score=0.9,
        reason="ok",
    )
    base.update(over)
    return _VerdictSchema(**base)


# --------------------------------------------------------------------------- verify
def test_verify_generated_fails_on_person(monkeypatch):
    _enable_verify(monkeypatch)
    _patch_provider(monkeypatch, _full_ok(person_present=True))  # everything else perfect
    v = iv.verify_generated_image(
        reference_bytes=b"ref", reference_content_type="image/png",
        candidate_bytes=b"cand", candidate_content_type="image/png",
        category="top", color="black", pattern=None, name="Tee",
    )
    assert v.matches is False          # a person is an unconditional fail
    assert v.person_present is True


def test_verify_generated_passes_when_person_free(monkeypatch):
    _enable_verify(monkeypatch)
    _patch_provider(monkeypatch, _full_ok(person_present=False))
    v = iv.verify_generated_image(
        reference_bytes=b"ref", reference_content_type="image/png",
        candidate_bytes=b"cand", candidate_content_type="image/png",
        category="top", color="black", pattern=None, name="Tee",
    )
    assert v.matches is True
    assert v.person_present is False


def test_verify_image_surfaces_on_model_without_failing(monkeypatch):
    _enable_verify(monkeypatch)
    # An on-model email photo of the right garment: matches stays True; person surfaced.
    _patch_provider(monkeypatch, _full_ok(person_present=True))
    v = iv.verify_image(
        image_bytes=b"img", content_type="image/jpeg",
        category="dress", color="red", name="Red Dress",
    )
    assert v.matches is True            # email verify does NOT fail on a person
    assert v.person_present is True     # ...it reports it so the resolver can route


# --------------------------------------------------------------------------- generate_core
def _gen_result():
    return GenerationResult(
        image_bytes=b"gen-bytes", content_type="image/png", provider="nano_banana",
        model="m", latency_s=0.1, cost_usd=0.13, detail="",
    )


def _budgets():
    return GenerationBudget(5), VerifyBudget(5), UsageAccumulator()


def test_generate_from_reference_stores_only_on_verified_pass(monkeypatch):
    gb, vb, usage = _budgets()
    monkeypatch.setattr(gc, "get_generation_provider",
                        lambda name=None: SimpleNamespace(generate=lambda req: _gen_result()))
    monkeypatch.setattr(gc, "_store", lambda sc, uid, data, ct: "https://cdn/gen.png")
    # verify passes (person-free) -> stored
    monkeypatch.setattr(gc, "verify_generated_image",
                        lambda **k: VerifyVerdict(True, True, True, 0.9, "ok", "m"))
    out = gc.generate_from_reference_bytes(
        reference_bytes=b"ref", reference_content_type="image/png",
        name="Tee", category="top", color="black", brand=None,
        storage_client=object(), user_id="u", gen_budget=gb, verify_budget=vb, usage=usage,
    )
    assert out.outcome == "ready" and out.url == "https://cdn/gen.png"


def test_generate_from_reference_held_when_verify_fails(monkeypatch):
    gb, vb, usage = _budgets()
    monkeypatch.setattr(gc, "get_generation_provider",
                        lambda name=None: SimpleNamespace(generate=lambda req: _gen_result()))
    monkeypatch.setattr(gc, "_store", lambda *a, **k: pytest.fail("must not store a rejected image"))
    # verify FAILS (e.g. a person survived into the candidate) -> never stored
    monkeypatch.setattr(gc, "verify_generated_image",
                        lambda **k: VerifyVerdict(False, True, True, 0.9, "person", "m", person_present=True))
    out = gc.generate_from_reference_bytes(
        reference_bytes=b"ref", reference_content_type="image/png",
        name="Tee", category="top", color="black", brand=None,
        storage_client=object(), user_id="u", gen_budget=gb, verify_budget=vb, usage=usage,
    )
    assert out.outcome == "held" and out.url is None


def test_generate_from_reference_budget_counts_calls(monkeypatch):
    """Cost cut #3: budget is consumed per ACTUAL generation call. With budget=1 and a
    verify that fails, the single unit is spent on the first rung's call and the second
    rung is budget-blocked — one call total, outcome 'held' (a real attempt was made)."""
    calls = {"n": 0}

    def _provider(name=None):
        def _gen(req):
            calls["n"] += 1
            return _gen_result()
        return SimpleNamespace(generate=_gen)

    monkeypatch.setattr(gc, "get_generation_provider", _provider)
    monkeypatch.setattr(gc, "verify_generated_image",
                        lambda **k: VerifyVerdict(False, True, True, 0.1, "no", "m"))
    out = gc.generate_from_reference_bytes(
        reference_bytes=b"ref", reference_content_type="image/png",
        name="Tee", category="top", color="black", brand=None,
        storage_client=object(), user_id="u",
        gen_budget=GenerationBudget(1), verify_budget=VerifyBudget(5), usage=UsageAccumulator(),
    )
    assert calls["n"] == 1          # ladder is 2 rungs, but budget bounded it to ONE call
    assert out.outcome == "held"    # a real attempt happened, it just missed verify


def test_generate_from_reference_zero_budget_is_budget(monkeypatch):
    monkeypatch.setattr(gc, "get_generation_provider",
                        lambda name=None: SimpleNamespace(
                            generate=lambda req: pytest.fail("must not generate with no budget")))
    out = gc.generate_from_reference_bytes(
        reference_bytes=b"ref", reference_content_type="image/png",
        name="Tee", category="top", color="black", brand=None,
        storage_client=object(), user_id="u",
        gen_budget=GenerationBudget(0), verify_budget=VerifyBudget(5), usage=UsageAccumulator(),
    )
    assert out.outcome == "budget"


def test_generate_from_text_requires_person_free(monkeypatch):
    import app.services.image_generation.nano_banana as nb

    gb, vb, usage = _budgets()
    monkeypatch.setattr(nb, "generate_text_to_image", lambda prompt, **k: _gen_result())
    monkeypatch.setattr(gc, "_store", lambda *a, **k: "https://cdn/t2i.png")
    # matches but a person present -> held (t2i enforces no-person explicitly)
    monkeypatch.setattr(gc, "verify_image",
                        lambda **k: VerifyVerdict(True, True, True, 0.9, "ok", "m", person_present=True))
    held = gc.generate_from_text(
        name="Tee", category="top", color="black", brand=None,
        storage_client=object(), user_id="u", gen_budget=GenerationBudget(5),
        verify_budget=vb, usage=usage,
    )
    assert held.outcome == "held"
    # person-free + matches -> stored
    monkeypatch.setattr(gc, "verify_image",
                        lambda **k: VerifyVerdict(True, True, True, 0.9, "ok", "m", person_present=False))
    ok = gc.generate_from_text(
        name="Tee", category="top", color="black", brand=None,
        storage_client=object(), user_id="u", gen_budget=GenerationBudget(5),
        verify_budget=VerifyBudget(5), usage=UsageAccumulator(),
    )
    assert ok.outcome == "ready" and ok.url == "https://cdn/t2i.png"


# --------------------------------------------------------------------------- on-model router
def test_route_on_model_returns_generated_on_success(monkeypatch):
    from app.gmail_closet.image_resolver import resolve as rz

    monkeypatch.setattr(gc, "generation_armed", lambda: True)
    monkeypatch.setattr(
        gc, "generate_from_reference_bytes",
        lambda **k: gc.GenOutcome("ready", url="https://cdn/onmodel-gen.png",
                                  content_sha256="abc", verify_score=0.9, cost_usd=0.13),
    )
    item = SimpleNamespace(name="Dress", category="dress", color="red", brand=None)
    fetch = SimpleNamespace(raw=b"onmodel", content_type="image/jpeg")
    out = rz._route_on_model(item, fetch, object(), "u", GenerationBudget(5), VerifyBudget(5), UsageAccumulator())
    assert out is not None and out.url == "https://cdn/onmodel-gen.png"


def test_route_on_model_returns_none_on_miss(monkeypatch):
    from app.gmail_closet.image_resolver import resolve as rz

    monkeypatch.setattr(gc, "generation_armed", lambda: True)
    monkeypatch.setattr(gc, "generate_from_reference_bytes", lambda **k: gc.GenOutcome("held"))
    item = SimpleNamespace(name="Dress", category="dress", color="red", brand=None)
    fetch = SimpleNamespace(raw=b"onmodel", content_type="image/jpeg")
    # miss -> None so the caller rejects the on-model original (never stored as fallback)
    assert rz._route_on_model(item, fetch, object(), "u", GenerationBudget(5), VerifyBudget(5), UsageAccumulator()) is None
