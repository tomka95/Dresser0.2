"""Unit tests for the generation bake-off script's PURE parts (offline).

The script is import-safe (all work lives under main()), so importing it here
runs nothing: no network, no DB, no keys. Generation + verify are never called —
cells are built directly through the same make_cell/verdict_to_dict helpers the
run loop uses. Covered: crop-slug/file naming, cost-preview math, aggregation
math (pass rates, logo-violation count, skipped-never-pass-nor-fail), and the
recommendation ordering (pass-rate > mean score > cost tiebreak).
"""
from app.gmail_closet.image_verify import VerifyVerdict

import scripts.dev_generation_bakeoff as bakeoff


# ---------------------------------------------------------------------------
# Cell builders (the same shape the run loop records)
# ---------------------------------------------------------------------------

def _verify(matches=True, skipped=False, logo_ok=True, pattern_ok=True, score=0.9):
    return {
        "skipped": skipped,
        "matches": matches,
        "garment_ok": True,
        "color_ok": True,
        "pattern_ok": pattern_ok,
        "logo_text_ok": logo_ok,
        "score": score,
        "reason": "",
        "model": "test-verify",
    }


def _cell(provider, idx=0, category="top", generated=True, verify=None,
          latency=5.0, cost=0.04, label="Black Halter Top"):
    return bakeoff.make_cell(
        crop_index=idx,
        label=label,
        slug=bakeoff.slugify(label),
        category=category,
        provider=provider,
        generated=generated,
        model="test-model" if generated else None,
        latency_s=latency if generated else None,
        cost_usd=cost if generated else None,
        output_file=f"{provider}/{idx:02d}_x.jpg" if generated else None,
        detail="" if generated else "generation failed",
        verify=verify,
    )


# ---------------------------------------------------------------------------
# Slug + file naming
# ---------------------------------------------------------------------------

def test_slugify_collapses_and_lowercases():
    assert bakeoff.slugify("Black Halter Top!") == "black-halter-top"
    assert bakeoff.slugify("  EZwear -- Crop  Top ") == "ezwear-crop-top"


def test_slugify_empty_and_none_fall_back():
    assert bakeoff.slugify("") == "item"
    assert bakeoff.slugify(None) == "item"
    assert bakeoff.slugify("!!!") == "item"


def test_slugify_truncates_without_trailing_dash():
    slug = bakeoff.slugify("a" * 39 + " bcd")
    assert len(slug) <= 40
    assert not slug.endswith("-")


def test_cell_filename_idx_slug_ext():
    assert bakeoff.cell_filename(3, "black-halter-top", "image/png") == "03_black-halter-top.png"
    assert bakeoff.cell_filename(0, "item", "image/jpeg") == "00_item.jpg"
    assert bakeoff.cell_filename(11, "x", "image/webp") == "11_x.webp"


def test_ext_for_unknown_content_type():
    assert bakeoff.ext_for("application/octet-stream") == "img"
    assert bakeoff.ext_for(None) == "img"
    assert bakeoff.ext_for("image/jpeg; charset=binary") == "jpg"


def test_parse_providers_normalizes_and_dedupes():
    assert bakeoff.parse_providers(" Flux_Kontext, seedream ,,flux_kontext") == [
        "flux_kontext",
        "seedream",
    ]
    assert bakeoff.parse_providers("") == []


# ---------------------------------------------------------------------------
# Cost-preview math
# ---------------------------------------------------------------------------

def test_estimate_cost_generation_plus_verify():
    rates = {"flux_kontext": 0.04, "seedream": 0.03}
    est = bakeoff.estimate_cost(3, ["flux_kontext", "seedream"], rates, include_verify=True)
    assert est["per_provider_usd"] == {"flux_kontext": 0.12, "seedream": 0.09}
    assert est["generation_usd"] == 0.21
    assert est["verify_usd"] == round(6 * bakeoff.VERIFY_USD_PER_PAIR, 6)
    assert est["total_usd"] == round(0.21 + 6 * bakeoff.VERIFY_USD_PER_PAIR, 6)


def test_estimate_cost_skip_verify_costs_nothing_extra():
    est = bakeoff.estimate_cost(5, ["seedream"], {"seedream": 0.03}, include_verify=False)
    assert est["verify_usd"] == 0.0
    assert est["total_usd"] == 0.15


# ---------------------------------------------------------------------------
# Verdict mapping
# ---------------------------------------------------------------------------

def test_verdict_to_dict_maps_all_fields():
    verdict = VerifyVerdict(
        matches=False, garment_ok=True, color_ok=True, score=0.55, reason="logo added",
        model="gemini-2.5-flash-lite", pattern_ok=True, logo_text_ok=False, skipped=False,
    )
    d = bakeoff.verdict_to_dict(verdict)
    assert d == {
        "skipped": False,
        "matches": False,
        "garment_ok": True,
        "color_ok": True,
        "pattern_ok": True,
        "logo_text_ok": False,
        "score": 0.55,
        "reason": "logo added",
        "model": "gemini-2.5-flash-lite",
    }


# ---------------------------------------------------------------------------
# Aggregation math
# ---------------------------------------------------------------------------

def test_provider_stats_mixed_outcomes():
    cells = [
        _cell("p", idx=0, verify=_verify(matches=True, score=0.9)),
        _cell("p", idx=1, verify=_verify(matches=False, logo_ok=False, score=0.4)),
        _cell("p", idx=2, verify=_verify(skipped=True, matches=False, score=0.0)),
        _cell("p", idx=3, generated=False),  # gen failure: no verify at all
    ]
    s = bakeoff.provider_stats(cells)
    assert s["attempts"] == 4
    assert s["generated"] == 3
    assert s["gen_fail"] == 1
    assert s["scored"] == 2
    assert s["verified_pass"] == 1
    assert s["verified_fail"] == 1
    assert s["verify_skipped"] == 1
    assert s["logo_violations"] == 1
    assert s["pattern_fails"] == 0
    # skipped verify excluded from the mean; gen failure counts in the denominator
    assert abs(s["mean_score"] - 0.65) < 1e-9
    assert abs(s["pass_rate"] - (1 / 3)) < 1e-9
    assert abs(s["mean_latency_s"] - 5.0) < 1e-9
    assert abs(s["total_cost_usd"] - 0.12) < 1e-9


def test_provider_stats_pattern_fail_counted():
    cells = [_cell("p", verify=_verify(matches=False, pattern_ok=False, score=0.3))]
    s = bakeoff.provider_stats(cells)
    assert s["pattern_fails"] == 1
    assert s["logo_violations"] == 0


def test_skipped_verifies_are_never_pass_nor_fail():
    cells = [
        _cell("p", idx=0, verify=_verify(skipped=True, matches=False, score=0.0)),
        _cell("p", idx=1, verify=_verify(skipped=True, matches=False, score=0.0)),
    ]
    s = bakeoff.provider_stats(cells)
    assert s["verified_pass"] == 0
    assert s["verified_fail"] == 0
    assert s["verify_skipped"] == 2
    assert s["pass_rate"] is None  # no scored evidence -> no verdict
    assert s["mean_score"] is None


def test_skip_verify_cells_are_unscored_not_skipped():
    # --skip-verify: verify never attempted (None) — neither scored nor skipped.
    cells = [_cell("p", idx=0, verify=None), _cell("p", idx=1, verify=None)]
    s = bakeoff.provider_stats(cells)
    assert s["scored"] == 0
    assert s["verify_skipped"] == 0
    assert s["pass_rate"] is None


def _account_skip_cell(provider, idx=0, category="top",
                       reason="no balance — top up at fal.ai/dashboard/billing"):
    # The shape _run_matrix records when a provider flags account unavailability.
    return bakeoff.make_cell(
        crop_index=idx, label="X", slug="x", category=category, provider=provider,
        generated=False, model=None, latency_s=None, cost_usd=None,
        output_file=None, detail=f"skipped: {reason}", verify=None, skip_reason=reason,
    )


def test_account_skip_is_not_generation_failure():
    # One pass + one account skip: the skip must NOT count as a gen-fail and must
    # NOT drag the pass-rate (a locked account is a billing state, not a result).
    cells = [
        _cell("p", idx=0, verify=_verify(matches=True, score=0.9)),
        _account_skip_cell("p", idx=1),
    ]
    s = bakeoff.provider_stats(cells)
    assert s["attempts"] == 2
    assert s["generated"] == 1
    assert s["gen_fail"] == 0            # account skip is NOT a generation failure
    assert s["provider_skipped"] == 1
    assert s["scored"] == 1
    assert abs(s["pass_rate"] - 1.0) < 1e-9   # 1/1, skip excluded from denominator


def test_account_skip_distinct_from_gen_fail_in_totals():
    # A real gen-fail and an account skip land in different buckets.
    cells = [
        _cell("p", idx=0, generated=False),   # honest generation failure
        _account_skip_cell("p", idx=1),       # account unavailable
    ]
    s = bakeoff.provider_stats(cells)
    assert s["gen_fail"] == 1
    assert s["provider_skipped"] == 1
    assert s["pass_rate"] is None         # nothing scored


def test_fully_account_skipped_provider_never_recommended():
    cells = [
        _account_skip_cell("a", idx=0),   # a: only account-skipped -> not eligible
        _cell("b", idx=0, verify=_verify(matches=False, score=0.3)),  # b: scored
    ]
    rec = bakeoff.recommend_defaults(cells, RATES, ["a", "b"])
    assert rec["overall"]["provider"] == "b"


def test_aggregate_categories_groups_none_as_unknown():
    cells = [
        _cell("p", idx=0, category="top", verify=_verify(score=0.8)),
        _cell("p", idx=1, category=None, verify=_verify(score=0.6)),
    ]
    cat_agg = bakeoff.aggregate_categories(cells, ["p"])
    assert set(cat_agg) == {"top", "unknown"}
    assert abs(cat_agg["top"]["p"]["mean_score"] - 0.8) < 1e-9
    assert abs(cat_agg["unknown"]["p"]["mean_score"] - 0.6) < 1e-9


# ---------------------------------------------------------------------------
# Recommendation ordering: pass-rate > mean score > cost
# ---------------------------------------------------------------------------

RATES = {"a": 0.04, "b": 0.03, "c": 0.134}


def test_recommend_pass_rate_beats_mean_score():
    cells = [
        # a: 2/2 pass at modest scores
        _cell("a", idx=0, verify=_verify(matches=True, score=0.7)),
        _cell("a", idx=1, verify=_verify(matches=True, score=0.7)),
        # b: 1/2 pass with one stellar score
        _cell("b", idx=0, verify=_verify(matches=True, score=0.99)),
        _cell("b", idx=1, verify=_verify(matches=False, score=0.2)),
    ]
    rec = bakeoff.recommend_defaults(cells, RATES, ["a", "b"])
    assert rec["overall"]["provider"] == "a"
    assert rec["per_category"]["top"]["provider"] == "a"
    assert rec["inconclusive"] is False


def test_recommend_mean_score_breaks_pass_rate_tie():
    cells = [
        _cell("a", idx=0, verify=_verify(matches=True, score=0.8)),
        _cell("b", idx=0, verify=_verify(matches=True, score=0.9)),
    ]
    rec = bakeoff.recommend_defaults(cells, RATES, ["a", "b"])
    assert rec["overall"]["provider"] == "b"


def test_recommend_cost_breaks_full_tie():
    cells = [
        _cell("a", idx=0, verify=_verify(matches=True, score=0.8)),
        _cell("b", idx=0, verify=_verify(matches=True, score=0.8)),
    ]
    rec = bakeoff.recommend_defaults(cells, RATES, ["a", "b"])
    assert rec["overall"]["provider"] == "b"  # $0.03 < $0.04


def test_recommend_gen_failures_hurt_pass_rate():
    cells = [
        # a: one pass, one generation failure -> pass_rate 1/2
        _cell("a", idx=0, verify=_verify(matches=True, score=0.9)),
        _cell("a", idx=1, generated=False),
        # b: one pass, one skipped verify -> pass_rate 1/1 (skips don't count)
        _cell("b", idx=0, verify=_verify(matches=True, score=0.7)),
        _cell("b", idx=1, verify=_verify(skipped=True, matches=False, score=0.0)),
    ]
    rec = bakeoff.recommend_defaults(cells, RATES, ["a", "b"])
    assert rec["overall"]["provider"] == "b"


def test_recommend_unscored_provider_never_recommended():
    cells = [
        # a: all verifies skipped — inconclusive, no matter what
        _cell("a", idx=0, verify=_verify(skipped=True, matches=False, score=0.0)),
        # b: one honest fail — scored, so it IS eligible (and wins by default)
        _cell("b", idx=0, verify=_verify(matches=False, score=0.3)),
    ]
    rec = bakeoff.recommend_defaults(cells, RATES, ["a", "b"])
    assert rec["overall"]["provider"] == "b"


def test_recommend_all_skipped_is_inconclusive():
    cells = [
        _cell("a", idx=0, verify=_verify(skipped=True, matches=False, score=0.0)),
        _cell("b", idx=0, verify=None),  # --skip-verify shape
    ]
    rec = bakeoff.recommend_defaults(cells, RATES, ["a", "b"])
    assert rec["overall"] is None
    assert rec["inconclusive"] is True
    assert rec["per_category"] == {"top": None}
    # And the rendered block says so instead of recommending anything.
    text = "\n".join(bakeoff.render_recommendations(rec))
    assert "INCONCLUSIVE" in text
    assert "flux" not in text and "a ->" not in text


def test_recommend_per_category_differs_from_overall():
    cells = [
        # tops: a perfect, b failing
        _cell("a", idx=0, category="top", verify=_verify(matches=True, score=0.9)),
        _cell("b", idx=0, category="top", verify=_verify(matches=False, score=0.3)),
        # bottoms: only b scored
        _cell("b", idx=1, category="bottom", verify=_verify(matches=True, score=0.8)),
        _cell("a", idx=1, category="bottom", verify=_verify(skipped=True, matches=False, score=0.0)),
    ]
    rec = bakeoff.recommend_defaults(cells, RATES, ["a", "b"])
    assert rec["per_category"]["top"]["provider"] == "a"
    assert rec["per_category"]["bottom"]["provider"] == "b"


# ---------------------------------------------------------------------------
# Rendering smoke (None-safe formatting; no crash on inconclusive columns)
# ---------------------------------------------------------------------------

def test_render_tables_handle_none_stats():
    cells = [
        _cell("a", idx=0, verify=_verify(matches=True, score=0.9)),
        _cell("b", idx=0, generated=False),  # b: no latency, no score, no pass_rate
    ]
    agg = bakeoff.aggregate_providers(cells, ["a", "b"])
    lines = bakeoff.render_provider_table(agg)
    assert any(line.startswith("a") for line in lines)
    assert any(line.startswith("b") for line in lines)
    cat_lines = bakeoff.render_category_table(
        bakeoff.aggregate_categories(cells, ["a", "b"]), ["a", "b"]
    )
    assert any("top" in line for line in cat_lines)
    md = bakeoff.render_markdown(
        {
            "timestamp_utc": "t",
            "crop_source": {"dir": "./crops"},
            "crops": [{}],
            "skip_verify": False,
        },
        {"estimated": {"total_usd": 0.05}, "actual_generation_usd": 0.04},
        agg,
        bakeoff.aggregate_categories(cells, ["a", "b"]),
        bakeoff.recommend_defaults(cells, RATES, ["a", "b"]),
        ["a", "b"],
    )
    assert "| a |" in md and "| b |" in md
    assert "Recommended defaults" in md
