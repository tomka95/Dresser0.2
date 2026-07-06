"""The interpretable Stage-1 score (Wave F2).

Pure functions: :class:`CandidateFeatures` + :class:`RankingConfig` → :class:`ScoreBreakdown`.
No DB, no LLM, no randomness — deterministic, so a fixed fixture pins every term (see
tests/test_ranker_golden.py) and a config weight change is a visible diff.

    score = w_taste·taste + w_gap·gap + w_price·price_fit + w_quality·quality − w_fatigue·fatigue

Each term is normalised to a comparable [0, 1] range BEFORE weighting so the weights alone
set the trade-off (taste cosine is remapped from [-1,1]; gap is per-user log-normalised by
the caller; price is a gaussian; fatigue is an exponential impression decay).
"""
from __future__ import annotations

import math
from typing import Iterable, List, Sequence

from app.ranking.types import (
    CandidateFeatures,
    RankingConfig,
    ScoreBreakdown,
    ScoredCandidate,
)


def taste_term(cosine_sim: float) -> float:
    """Remap a cosine in [-1, 1] to [0, 1]. A product orthogonal to the taste blend scores
    0.5; aligned → 1.0; opposed → 0.0."""
    return max(0.0, min(1.0, (float(cosine_sim) + 1.0) / 2.0))


def gap_term(unlock_count: int, fills_empty_occasion: bool, gap_norm: float, cfg: RankingConfig) -> float:
    """log(1+unlock_count) normalised per user (÷ gap_norm), plus an occasion-gap bonus
    when the product fills an L1 occasion the closet covers zero of. Clamped to [0, 1].

    ``gap_norm`` = log(1 + max unlock_count across the user's candidate pool), passed in by
    the caller so the busiest unlocker maps to ~1.0 and everything scales beneath it."""
    base = math.log1p(max(0, unlock_count))
    norm = base / gap_norm if gap_norm > 0 else 0.0
    if fills_empty_occasion:
        norm += cfg.gap_occasion_bonus
    return max(0.0, min(1.0, norm))


def price_term(price, budget_center, cfg: RankingConfig) -> float:
    """Gaussian fit to the budget band: 1.0 at the centre, decaying with |price − centre|.
    Neutral (cfg.price_neutral) when price or the band is unknown — an unpriced product is
    neither rewarded nor punished on price."""
    if price is None or budget_center is None or budget_center <= 0:
        return cfg.price_neutral
    sigma = max(1e-6, cfg.price_sigma_frac * budget_center)
    z = (float(price) - float(budget_center)) / sigma
    return math.exp(-0.5 * z * z)


def quality_term(quality_recency: float) -> float:
    """Already computed in [0, 1] by the feature layer (freshness + in-stock + verified
    image). Passed through, clamped."""
    return max(0.0, min(1.0, float(quality_recency)))


def fatigue_term(impressions: int, cfg: RankingConfig) -> float:
    """Impression fatigue in [0, 1]: 1 − exp(−decay·impressions). 0 for an unseen product,
    saturating toward 1 the more it has been shown. Subtracted (weighted) from the score."""
    return 1.0 - math.exp(-cfg.fatigue_decay * max(0, impressions))


def score_candidate(
    f: CandidateFeatures,
    cfg: RankingConfig,
    *,
    gap_norm: float,
) -> ScoreBreakdown:
    """Full score for one candidate. Each returned term is ALREADY weight-scaled so the
    breakdown sums (with fatigue subtracted) to ``total``."""
    taste = cfg.w_taste * taste_term(f.taste_match)
    gap = cfg.w_gap * gap_term(f.unlock_count, f.fills_empty_occasion, gap_norm, cfg)
    price = cfg.w_price * price_term(f.price, f.budget_center, cfg)
    quality = cfg.w_quality * quality_term(f.quality_recency)
    fatigue_raw = fatigue_term(f.impressions, cfg)
    total = taste + gap + price + quality - cfg.w_fatigue * fatigue_raw
    return ScoreBreakdown(
        taste=taste,
        gap=gap,
        price=price,
        quality=quality,
        fatigue=fatigue_raw,
        total=total,
    )


def gap_norm_for(features: Iterable[CandidateFeatures]) -> float:
    """Per-user normaliser: log(1 + max unlock_count). Never returns 0 (so gap_term's ÷ is
    safe) — a pool with no unlocks yields 1.0 and every gap term is then 0."""
    mx = 0
    for f in features:
        if f.unlock_count > mx:
            mx = f.unlock_count
    return math.log1p(mx) or 1.0


def score_all(features: Sequence[CandidateFeatures], cfg: RankingConfig) -> List[ScoredCandidate]:
    """Score a whole candidate pool, sorted by total desc (deterministic tie-break on
    product_id). The gap normaliser is derived from the pool so it is comparable across it."""
    gnorm = gap_norm_for(features)
    scored = [
        ScoredCandidate(features=f, breakdown=score_candidate(f, cfg, gap_norm=gnorm))
        for f in features
    ]
    scored.sort(key=lambda s: (-s.score, s.product_id))
    return scored
