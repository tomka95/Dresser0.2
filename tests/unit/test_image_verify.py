"""Unit tests for the vision-verify post-processing (offline — Gemini is stubbed).

These exercise app.gmail_closet.image_verify.verify_image's trust logic WITHOUT a
real model call: a fake AIProvider returns a canned structured verdict, and we assert
how verify_image folds it into the final VerifyVerdict — in particular the
no-expected-color override (color can't be a failure criterion when there's no
expected color to check against).
"""
import app.services.ai_provider as ai_provider
from app.gmail_closet.image_verify import _VerdictSchema, verify_image


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
