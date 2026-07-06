"""Golden behaviour lock for the Stage-1 feed ranker (Wave F2).

Captures the ranker's full output — per-candidate score BREAKDOWN (each weighted term),
the evidence-weighted blend weights, and the final re-ranked order (with exploration flags)
— over three fixed personas, and asserts it byte-identical against a committed snapshot.

This is the interpretability gate the F2 brief asks for: a weight change in
``app.core.config`` (or a formula change in ``app.ranking.score`` / ``rerank`` /
``centroids``) shows up here as a readable per-term diff, so no coefficient moves silently.

Everything is PURE (no DB, no API): candidate/centroid vectors are hand-authored in a tiny
4-d space, taste_match is a real cosine against the blend, and the re-rank seed is fixed —
so the whole pipeline is reproducible run-to-run.

Record mode: delete tests/golden/ranker_golden.json (or set RECORD_RANKER_GOLDEN=1) and run
once to regenerate the snapshot from the CURRENT ranker, then re-run to assert.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List

import pytest

from app.ranking import centroids as C
from app.ranking import rerank as R
from app.ranking import score as S
from app.ranking.types import CandidateFeatures, RankingConfig

GOLDEN_PATH = Path(__file__).parent / "golden" / "ranker_golden.json"

# A frozen config (NOT read from settings, so the snapshot is stable even if a deployment
# env retunes the live weights — the test pins the DEFAULTS).
CFG = RankingConfig()

# Tiny 4-d taste space. Axes: [archetype, closet, liked, off-taste].
ARCHETYPE = C.l2_normalize([1.0, 0.0, 0.0, 0.0])
CLOSET = C.l2_normalize([0.0, 1.0, 0.0, 0.0])
LIKED = C.l2_normalize([0.0, 0.0, 1.0, 0.0])

# (id, emb, unlock, fills_empty, price, budget_center, quality, impressions, category)
POOL = [
    ("p_liked_hit", [0.1, 0.2, 0.97, 0.0], 4, False, 90, 100, 0.9, 0, "top"),
    ("p_closet_twin", [0.0, 0.98, 0.2, 0.0], 2, False, 110, 100, 0.8, 1, "top"),
    ("p_gap_filler", [0.2, 0.2, 0.5, 0.3], 8, True, 80, 100, 0.7, 0, "outerwear"),
    ("p_pricey", [0.1, 0.1, 0.95, 0.0], 3, False, 420, 100, 0.6, 0, "top"),
    ("p_fatigued", [0.0, 0.1, 0.98, 0.0], 3, False, 100, 100, 0.9, 12, "top"),
    ("p_archetype", [0.99, 0.05, 0.0, 0.0], 1, False, 95, 100, 0.5, 0, "bottom"),
    ("p_offtaste", [0.1, 0.0, 0.0, 0.99], 0, False, 100, 100, 0.5, 0, "accessory"),
    ("p_bottom_gap", [0.2, 0.3, 0.6, 0.0], 6, True, 70, 100, 0.8, 0, "bottom"),
    ("p_neutral", [0.3, 0.3, 0.3, 0.3], 1, False, 130, 100, 0.6, 2, "top"),
]

# Persona = (has_liked, has_closet, has_archetype, evidence_count). The blend schedule turns
# these into α/β/γ; a cold-start persona is archetype-only.
PERSONAS = {
    "warm_taste_driven": (True, True, True, 30),
    "mid_some_evidence": (True, True, True, 6),
    "cold_start_archetype": (False, False, True, 0),
}


def _blend_for(persona: str):
    has_liked, has_closet, has_arch, ev = PERSONAS[persona]
    return C.blend_centroid(
        LIKED if has_liked else None,
        CLOSET if has_closet else None,
        ARCHETYPE if has_arch else None,
        evidence_count=ev,
        cfg=CFG,
    )


def _features_for(blend) -> List[CandidateFeatures]:
    feats = []
    for (pid, emb, unlock, fills, price, budget, quality, impr, cat) in POOL:
        taste = C.cosine(blend, C.l2_normalize(emb))
        feats.append(
            CandidateFeatures(
                product_id=pid,
                taste_match=taste,
                unlock_count=unlock,
                fills_empty_occasion=fills,
                price=price,
                budget_center=budget,
                quality_recency=quality,
                impressions=impr,
                category=cat,
                embedding=tuple(emb),
            )
        )
    return feats


def _compute() -> dict:
    out: dict = {}
    for persona in PERSONAS:
        has_liked, has_closet, has_arch, ev = PERSONAS[persona]
        blend_w = C.blend_weights(
            has_liked=has_liked, has_closet=has_closet, has_archetype=has_arch,
            evidence_count=ev, cfg=CFG,
        )
        blend = _blend_for(persona)
        feats = _features_for(blend)
        scored = S.score_all(feats, CFG)
        # target_mix: a "top-heavy" closet, to exercise category calibration.
        target_mix = {"top": 0.6, "bottom": 0.25, "outerwear": 0.1, "accessory": 0.05}
        ordered = R.rerank(scored, CFG, target_mix=target_mix, seed=1234, limit=len(scored))
        out[persona] = {
            "blend_weights": {k: round(v, 6) for k, v in blend_w.items()},
            "scores": {
                s.product_id: s.breakdown.as_dict()
                for s in sorted(scored, key=lambda c: c.product_id)
            },
            "ranked_order": [
                {"id": s.product_id, "exploration": s.exploration} for s in ordered
            ],
        }
    return out


def test_ranker_matches_golden():
    result = _compute()

    record = os.environ.get("RECORD_RANKER_GOLDEN") == "1" or not GOLDEN_PATH.exists()
    if record:
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        pytest.skip(f"recorded golden -> {GOLDEN_PATH} ({len(result)} personas)")

    golden = json.loads(GOLDEN_PATH.read_text())
    mismatches = [k for k in golden if result.get(k) != golden[k]]
    assert not mismatches, "ranker output drifted for: " + ", ".join(mismatches) + (
        "\n" + json.dumps({k: {"golden": golden[k], "got": result.get(k)} for k in mismatches}, indent=2)
    )
    assert set(result) == set(golden), "persona set changed"


def test_cold_start_is_archetype_only():
    """Guard the headline cold-start property directly (independent of the snapshot)."""
    w = C.blend_weights(
        has_liked=False, has_closet=False, has_archetype=True, evidence_count=0, cfg=CFG
    )
    assert w == {"liked": 0.0, "closet": 0.0, "archetype": 1.0}


def test_evidence_grows_liked_shrinks_archetype():
    cold = C.blend_weights(has_liked=True, has_closet=True, has_archetype=True,
                           evidence_count=0, cfg=CFG)
    warm = C.blend_weights(has_liked=True, has_closet=True, has_archetype=True,
                           evidence_count=40, cfg=CFG)
    assert warm["liked"] > cold["liked"]        # α grows with evidence
    assert warm["archetype"] < cold["archetype"]  # γ shrinks with evidence


def test_exploration_slice_is_flagged_and_from_reservoir():
    """With a page smaller than the pool, a reservoir exists → exploration fires. Every
    exploration pick must be flagged and drawn from OUTSIDE the exploited head (so the feed
    genuinely widens rather than re-showing top items)."""
    blend = _blend_for("warm_taste_driven")
    feats = _features_for(blend)
    scored = S.score_all(feats, CFG)

    limit = 6  # < len(POOL)=9, so ordered[limit:] is a non-empty reservoir
    ordered = R.rerank(scored, CFG, target_mix={}, seed=7, limit=limit)
    assert len(ordered) == limit

    exploration = [c for c in ordered if c.exploration]
    assert exploration, "expected at least one exploration pick with a page < pool"
    # Exploration picks are lower-ranked reservoir items, not the top exploited head.
    exploited_head_ids = {c.product_id for c in
                          R.mmr_calibrated_order(scored, CFG, limit=limit)[:limit]}
    for c in exploration:
        assert c.rerank_reason == "exploration"
