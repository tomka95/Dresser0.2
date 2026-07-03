"""Verify cost telemetry is priced at the MODEL that ran each verify call.

The single-image pass runs Flash-Lite (GMAIL_VERIFY_MODEL); the generated-image
reference-vs-candidate PAIR pass runs the pricier GENERATION_VERIFY_MODEL (Flash).
add_verify must price each call at its own model so a mix is not under-reported.
"""
from app.core.config import settings
from app.gmail_closet.usage import UsageAccumulator, gemini_cost


def test_single_image_verify_prices_at_flash_lite_unchanged():
    """Default add_verify (no model) prices at GMAIL_VERIFY_MODEL (Flash-Lite) —
    the single-image path's pricing is exactly as before this change."""
    acc = UsageAccumulator()
    acc.add_verify(1000, 500)
    assert acc.verify_cost_usd == gemini_cost(settings.GMAIL_VERIFY_MODEL, 1000, 500)
    # Token totals still recorded for the count columns.
    assert acc.verify_input_tokens == 1000
    assert acc.verify_output_tokens == 500


def test_pair_verify_prices_at_flash_not_flash_lite():
    """The pair pass (model=GENERATION_VERIFY_MODEL) prices at Flash — strictly more
    than the Flash-Lite rate for the same tokens (the bug being fixed)."""
    tokens = (1000, 500)
    flash = UsageAccumulator()
    flash.add_verify(*tokens, model=settings.GENERATION_VERIFY_MODEL)
    lite = UsageAccumulator()
    lite.add_verify(*tokens)  # single-image default
    assert flash.verify_cost_usd == gemini_cost(settings.GENERATION_VERIFY_MODEL, *tokens)
    assert flash.verify_cost_usd > lite.verify_cost_usd


def test_mixed_models_sum_per_model():
    """One single-image call + one pair call accrue at their own rates and sum."""
    acc = UsageAccumulator()
    acc.add_verify(1000, 500)                                        # Flash-Lite
    acc.add_verify(2000, 800, model=settings.GENERATION_VERIFY_MODEL)  # Flash
    expected = (
        gemini_cost(settings.GMAIL_VERIFY_MODEL, 1000, 500)
        + gemini_cost(settings.GENERATION_VERIFY_MODEL, 2000, 800)
    )
    assert abs(acc.verify_cost_usd - expected) < 1e-12
    assert acc.verify_input_tokens == 3000
    assert acc.verify_output_tokens == 1300
