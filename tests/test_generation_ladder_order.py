"""The RESOLVED generation ladder order — flux2_pro first, nano_banana fallback.

Forensics (2026-07-10) found nano_banana dominating ~95% of Gemini spend and
asked whether the ladder had silently regressed to nano-first. It had not:
runtime tracing (live BFL calls, see the day's session notes) confirmed
flux2_pro fires first and succeeds; nano only gets invoked when a downstream
step (verify) can't complete — by design, not a ladder-order bug. This test
pins the resolved order so a REAL regression (someone reordering the tuple,
or a provider dispatch bug) fails CI, not just a live call days later.
"""
from __future__ import annotations

from app.photo_closet import generation_service as photo_gen
from app.services.image_generation import generate_core


def test_shared_core_ladder_is_flux2_first_nano_fallback():
    assert generate_core._LADDER == ("flux2_pro", "nano_banana")
    assert generate_core._LADDER[0] == "flux2_pro"
    assert generate_core._LADDER[-1] == "nano_banana"


def test_photo_pipeline_has_no_local_ladder_and_defaults_to_none():
    """Photo-seam Phase 1: the photo path deletes its own ladder and delegates to
    the shared core with ladder=None, which generate_from_reference_bytes
    resolves to `ladder or _LADDER` — i.e. the SAME flux2-first tuple. Asserting
    'no local ladder' is the regression guard: a reintroduced
    _GENERATION_LADDER constant here would be exactly how this class of bug
    reappears silently."""
    assert not hasattr(photo_gen, "_GENERATION_LADDER")
    assert not hasattr(photo_gen, "_LADDER")


def test_generate_from_reference_bytes_default_ladder_param_is_shared_core(monkeypatch):
    """Call the seam with no explicit ladder (exactly how every real caller —
    photo worker, self-heal, manual, gmail on-model routing — invokes it) and
    assert the FIRST provider resolved is flux2_pro, never nano_banana, by
    intercepting get_generation_provider (no network)."""
    from uuid import uuid4

    from app.gmail_closet.image_verify import VerifyBudget
    from app.platform.usage import UsageAccumulator
    from app.services.image_generation.base import GenerationBudget

    resolved_order = []

    class _Miss:
        def generate(self, req):
            return None

    def _spy_get_provider(name=None):
        resolved_order.append(name)
        return _Miss()

    monkeypatch.setattr(generate_core, "get_generation_provider", _spy_get_provider)

    generate_core.generate_from_reference_bytes(
        reference_bytes=b"x", reference_content_type="image/png",
        name="Tee", category="top", color="red", brand=None,
        storage_client=None, user_id=uuid4(),
        gen_budget=GenerationBudget(5), verify_budget=VerifyBudget(5),
        usage=UsageAccumulator(),
    )

    assert resolved_order == ["flux2_pro", "nano_banana"]
