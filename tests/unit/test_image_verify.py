"""Unit tests for the vision-verify post-processing (offline — Gemini is stubbed).

These exercise app.gmail_closet.image_verify.verify_image's trust logic WITHOUT a
real model call: a fake AIProvider returns a canned structured verdict, and we assert
how verify_image folds it into the final VerifyVerdict — in particular the
no-expected-color override (color can't be a failure criterion when there's no
expected color to check against).

Wave 2 additions exercise verify_generated_image (the TWO-image reference-vs-
generated pass) the same way: image ordering, the pattern_ok / logo_text_ok gates,
the threshold fold, skip semantics, and the media-resolution setting mapping.
"""
import logging

import app.services.ai_provider as ai_provider
from app.core.config import settings
from app.gmail_closet.image_verify import (
    VerifyBudget,
    _generation_media_resolution,
    _VerdictSchema,
    verify_generated_image,
    verify_image,
)


class _FakeResp:
    def __init__(self, parsed: _VerdictSchema):
        self.parsed = parsed
        self.text = None


class _FakeProvider:
    def __init__(self, verdict: _VerdictSchema):
        self._verdict = verdict

    def generate_structured(self, **kwargs):
        return _FakeResp(self._verdict)


def _stub_model(monkeypatch, *, garment_ok, color_ok, score=0.9):
    """Make verify_image see a canned model verdict (matches is intentionally the
    model's raw value; verify_image must recompute the real decision itself)."""
    verdict = _VerdictSchema(
        garment_ok=garment_ok,
        color_ok=color_ok,
        matches=bool(garment_ok and color_ok),
        score=score,
        reason="stub",
    )
    monkeypatch.setattr(ai_provider, "get_ai_provider", lambda: _FakeProvider(verdict))


def test_blank_color_passes_on_garment(monkeypatch):
    """No expected color + correct garment -> PASS, even if the model said color_ok=false."""
    _stub_model(monkeypatch, garment_ok=True, color_ok=False)
    v = verify_image(
        image_bytes=b"\xff\xd8\xff_fake", content_type="image/jpeg",
        category="top", color="   ", name="Halter Top",
    )
    assert v.matches is True
    assert v.color_ok is True  # forced true: no criterion to fail on


def test_none_color_passes_on_garment(monkeypatch):
    """None expected color is treated the same as blank."""
    _stub_model(monkeypatch, garment_ok=True, color_ok=False)
    v = verify_image(
        image_bytes=b"\xff\xd8\xff_fake", content_type="image/jpeg",
        category="top", color=None, name="Halter Top",
    )
    assert v.matches is True
    assert v.color_ok is True


def test_present_but_wrong_color_fails(monkeypatch):
    """Expected color present + wrong color family -> FAIL (cross-colorway guard kept)."""
    _stub_model(monkeypatch, garment_ok=True, color_ok=False)
    v = verify_image(
        image_bytes=b"\xff\xd8\xff_fake", content_type="image/jpeg",
        category="top", color="black", name="Halter Top",
    )
    assert v.matches is False
    assert v.color_ok is False


def test_present_correct_color_passes(monkeypatch):
    """Expected color present + matching color -> PASS (unchanged behavior)."""
    _stub_model(monkeypatch, garment_ok=True, color_ok=True)
    v = verify_image(
        image_bytes=b"\xff\xd8\xff_fake", content_type="image/jpeg",
        category="top", color="black", name="Halter Top",
    )
    assert v.matches is True
    assert v.color_ok is True


def test_blank_color_still_fails_on_garment(monkeypatch):
    """The override only neutralizes color — a garment mismatch still FAILS."""
    _stub_model(monkeypatch, garment_ok=False, color_ok=True)
    v = verify_image(
        image_bytes=b"\xff\xd8\xff_fake", content_type="image/jpeg",
        category="top", color="", name="Banner",
    )
    assert v.matches is False


# ---------------------------------------------------------------------------
# Back-compat: single-image verdicts carry pattern/logo True defaults
# ---------------------------------------------------------------------------

def test_verify_image_verdict_defaults_pattern_and_logo_true(monkeypatch):
    """The Wave-2 fields exist on single-image verdicts but default True — the
    single-image decision is still exactly garment AND color AND threshold."""
    _stub_model(monkeypatch, garment_ok=True, color_ok=True)
    v = verify_image(
        image_bytes=b"\xff\xd8\xff_fake", content_type="image/jpeg",
        category="top", color="black", name="Halter Top",
    )
    assert v.matches is True
    assert v.pattern_ok is True
    assert v.logo_text_ok is True


# ---------------------------------------------------------------------------
# Wave 2: verify_generated_image (reference + candidate pair)
# ---------------------------------------------------------------------------

class _CapturingProvider:
    """Fake provider that records every generate_structured call's kwargs."""

    def __init__(self, verdict: _VerdictSchema):
        self._verdict = verdict
        self.calls = []

    def generate_structured(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResp(self._verdict)


class _ExplodingProvider:
    def generate_structured(self, **kwargs):
        raise RuntimeError("boom")


def _stub_pair_model(
    monkeypatch, *, garment_ok=True, color_ok=True, pattern_ok=True,
    logo_text_ok=True, matches=None, score=0.9,
) -> _CapturingProvider:
    """Canned pair verdict. `matches` defaults to the AND of the four oks; pass an
    explicit (lying) value to prove verify_generated_image recomputes in code."""
    verdict = _VerdictSchema(
        garment_ok=garment_ok,
        color_ok=color_ok,
        pattern_ok=pattern_ok,
        logo_text_ok=logo_text_ok,
        matches=(
            bool(garment_ok and color_ok and pattern_ok and logo_text_ok)
            if matches is None else matches
        ),
        score=score,
        reason="stub",
    )
    provider = _CapturingProvider(verdict)
    monkeypatch.setattr(ai_provider, "get_ai_provider", lambda: provider)
    return provider


def _call_pair(**overrides):
    kwargs = dict(
        reference_bytes=b"REFERENCE_bytes", reference_content_type="image/png",
        candidate_bytes=b"CANDIDATE_bytes", candidate_content_type="image/jpeg",
        category="top", color="black", pattern="solid", name="Halter Top",
    )
    kwargs.update(overrides)
    return verify_generated_image(**kwargs)


def test_pair_sends_two_images_reference_first(monkeypatch):
    """Exactly TWO image parts, reference first, candidate second — matching the
    'Image 1 = reference' labeling in the prompt. Default media resolution MEDIUM."""
    from google.genai import types

    provider = _stub_pair_model(monkeypatch)
    v = _call_pair()
    assert v.matches is True
    assert v.skipped is False

    (call,) = provider.calls
    parts = call["image_parts"]
    assert len(parts) == 2
    assert parts[0]["inline_data"]["data"] == b"REFERENCE_bytes"
    assert parts[0]["inline_data"]["mime_type"] == "image/png"
    assert parts[1]["inline_data"]["data"] == b"CANDIDATE_bytes"
    assert parts[1]["inline_data"]["mime_type"] == "image/jpeg"
    assert "Image 1 = reference" in call["user_text"]
    assert call["media_resolution"] == types.MediaResolution.MEDIA_RESOLUTION_MEDIUM


def test_pair_logo_text_fail_blocks_even_with_high_score(monkeypatch):
    """logo_text_ok=false is a hard fail — even at score 0.99 and even when the
    model's raw `matches` lies true (the decision is recomputed in code)."""
    _stub_pair_model(monkeypatch, logo_text_ok=False, matches=True, score=0.99)
    v = _call_pair()
    assert v.matches is False
    assert v.logo_text_ok is False
    assert v.skipped is False


def test_pair_pattern_fail_blocks_even_with_high_score(monkeypatch):
    """pattern_ok=false is a hard fail too (solid must stay solid, etc.)."""
    _stub_pair_model(monkeypatch, pattern_ok=False, matches=True, score=0.99)
    v = _call_pair()
    assert v.matches is False
    assert v.pattern_ok is False
    assert v.skipped is False


def test_pair_threshold_fold(monkeypatch):
    """All four oks true but score below GMAIL_VERIFY_SCORE_THRESHOLD -> FAIL;
    at/above threshold -> PASS."""
    monkeypatch.setattr(settings, "GMAIL_VERIFY_SCORE_THRESHOLD", 0.6, raising=False)

    _stub_pair_model(monkeypatch, score=0.59)
    assert _call_pair().matches is False

    _stub_pair_model(monkeypatch, score=0.6)
    assert _call_pair().matches is True


def test_pair_disabled_skips(monkeypatch):
    """GMAIL_VERIFY_ENABLED=false -> skipped, not matched, no provider call."""
    provider = _stub_pair_model(monkeypatch)
    monkeypatch.setattr(settings, "GMAIL_VERIFY_ENABLED", False, raising=False)
    v = _call_pair()
    assert v.matches is False
    assert v.skipped is True
    assert provider.calls == []


def test_pair_budget_exhausted_skips(monkeypatch):
    """An exhausted VerifyBudget -> skipped, not matched, no provider call."""
    provider = _stub_pair_model(monkeypatch)
    v = _call_pair(budget=VerifyBudget(0))
    assert v.matches is False
    assert v.skipped is True
    assert provider.calls == []


def test_pair_budget_consumed_when_available(monkeypatch):
    """A live budget is consumed by the pair call (same cost guard as verify_image)."""
    _stub_pair_model(monkeypatch)
    budget = VerifyBudget(1)
    v = _call_pair(budget=budget)
    assert v.matches is True
    assert budget.remaining == 0


def test_pair_provider_error_skips(monkeypatch):
    """Any provider exception -> matches=false + skipped=true, never raises."""
    monkeypatch.setattr(ai_provider, "get_ai_provider", lambda: _ExplodingProvider())
    v = _call_pair()
    assert v.matches is False
    assert v.skipped is True


# ---------------------------------------------------------------------------
# GENERATION_VERIFY_MEDIA_RESOLUTION mapping
# ---------------------------------------------------------------------------

def test_media_resolution_mapping_low_medium_high(monkeypatch):
    from google.genai import types

    for raw, want in (
        ("low", types.MediaResolution.MEDIA_RESOLUTION_LOW),
        ("medium", types.MediaResolution.MEDIA_RESOLUTION_MEDIUM),
        ("HIGH", types.MediaResolution.MEDIA_RESOLUTION_HIGH),  # case-insensitive
    ):
        monkeypatch.setattr(
            settings, "GENERATION_VERIFY_MEDIA_RESOLUTION", raw, raising=False
        )
        assert _generation_media_resolution(types) == want


def test_media_resolution_bad_value_falls_back_to_medium(monkeypatch, caplog):
    from google.genai import types

    monkeypatch.setattr(
        settings, "GENERATION_VERIFY_MEDIA_RESOLUTION", "ultra", raising=False
    )
    with caplog.at_level(logging.WARNING, logger="app.gmail_closet.image_verify"):
        got = _generation_media_resolution(types)
    assert got == types.MediaResolution.MEDIA_RESOLUTION_MEDIUM
    assert any(
        "GENERATION_VERIFY_MEDIA_RESOLUTION" in r.getMessage() for r in caplog.records
    )
