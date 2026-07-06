"""Ranker value types + the interpretable weight bundle (Wave F2).

Pure data. No DB, no LLM, no import of ``app.monetization`` (import-linter wall). These
dataclasses are the contract between the DB-bound feature layer (``features.py`` /
``gap.py``) and the pure scoring/re-rank core (``score.py`` / ``rerank.py``): the feature
layer produces :class:`CandidateFeatures`, the core turns them into a :class:`ScoredCandidate`
with a fully broken-out :class:`ScoreBreakdown`. The split is what makes the scoring
golden-testable with hand-authored numbers (see tests/test_ranker_golden.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class RankingConfig:
    """Every ranker coefficient, read once from ``app.core.config.settings``.

    Kept as a frozen bundle (not read ad-hoc from ``settings`` deep in the math) so the
    golden test can construct an EXPLICIT config and a weight change is a visible diff.
    """

    # score = w_taste·taste + w_gap·gap + w_price·price + w_quality·quality − w_fatigue·fatigue
    w_taste: float = 0.40
    w_gap: float = 0.25
    w_price: float = 0.15
    w_quality: float = 0.12
    w_fatigue: float = 0.18

    # taste-blend schedule
    blend_alpha: float = 0.60
    blend_beta: float = 0.40
    blend_gamma: float = 0.15
    blend_evidence_scale: float = 8.0

    # signal shaping
    gap_occasion_bonus: float = 0.25
    price_sigma_frac: float = 0.5
    price_neutral: float = 0.5
    fatigue_decay: float = 0.35

    # re-rank
    mmr_lambda: float = 0.70
    exploration_epsilon: float = 0.18
    category_calibration: float = 0.5

    # composition
    outfit_card_ratio: float = 0.30
    feed_page_size: int = 24
    outfit_min_closet: int = 4

    # gap-job combinatorics caps
    gap_candidate_k: int = 400
    gap_slot_top_m: int = 15

    @classmethod
    def from_settings(cls, settings) -> "RankingConfig":
        return cls(
            w_taste=settings.RANKING_W_TASTE,
            w_gap=settings.RANKING_W_GAP,
            w_price=settings.RANKING_W_PRICE,
            w_quality=settings.RANKING_W_QUALITY,
            w_fatigue=settings.RANKING_W_FATIGUE,
            blend_alpha=settings.RANKING_BLEND_ALPHA,
            blend_beta=settings.RANKING_BLEND_BETA,
            blend_gamma=settings.RANKING_BLEND_GAMMA,
            blend_evidence_scale=settings.RANKING_BLEND_EVIDENCE_SCALE,
            gap_occasion_bonus=settings.RANKING_GAP_OCCASION_BONUS,
            price_sigma_frac=settings.RANKING_PRICE_SIGMA_FRAC,
            price_neutral=settings.RANKING_PRICE_NEUTRAL,
            fatigue_decay=settings.RANKING_FATIGUE_DECAY,
            mmr_lambda=settings.RANKING_MMR_LAMBDA,
            exploration_epsilon=settings.RANKING_EXPLORATION_EPSILON,
            category_calibration=settings.RANKING_CATEGORY_CALIBRATION,
            outfit_card_ratio=settings.RANKING_OUTFIT_CARD_RATIO,
            feed_page_size=settings.RANKING_FEED_PAGE_SIZE,
            outfit_min_closet=settings.RANKING_OUTFIT_MIN_CLOSET,
            gap_candidate_k=settings.RANKING_GAP_CANDIDATE_K,
            gap_slot_top_m=settings.RANKING_GAP_SLOT_TOP_M,
        )


@dataclass(frozen=True)
class CandidateFeatures:
    """The per-product inputs the pure scorer consumes.

    Everything here is already resolved by the feature layer: ``taste_match`` is the raw
    cosine in [-1, 1]; ``unlock_count`` / ``fills_empty_occasion`` come from the
    user_wardrobe_gap row; ``price`` + ``budget_center`` frame the price gaussian;
    ``quality_recency`` is precomputed in [0, 1]; ``impressions`` drives fatigue.
    ``embedding`` (unit vector) is carried through for the MMR re-rank only.
    """

    product_id: str
    taste_match: float                         # raw cosine [-1, 1]
    unlock_count: int = 0
    fills_empty_occasion: bool = False
    price: Optional[float] = None
    budget_center: Optional[float] = None      # None → price scores neutral
    quality_recency: float = 0.5               # [0, 1]
    impressions: int = 0
    category: Optional[str] = None
    embedding: Optional[Tuple[float, ...]] = None


@dataclass(frozen=True)
class ScoreBreakdown:
    """The scalar terms of one product's score — each already weight-scaled.

    ``total`` is their signed sum. Exposed (and snapshotted by the golden test) so a
    weight change shows up term-by-term, not just as a moved final number.
    """

    taste: float
    gap: float
    price: float
    quality: float
    fatigue: float          # the RAW penalty in [0, 1] (subtracted, weighted, in total)
    total: float

    def as_dict(self) -> dict:
        return {
            "taste": round(self.taste, 6),
            "gap": round(self.gap, 6),
            "price": round(self.price, 6),
            "quality": round(self.quality, 6),
            "fatigue": round(self.fatigue, 6),
            "total": round(self.total, 6),
        }


@dataclass
class ScoredCandidate:
    """A candidate after scoring, before/after re-rank. ``exploration`` is set by the
    re-rank layer when this position is an exploration pick (flagged into the impression
    event so its engagement can be measured apart from exploited positions)."""

    features: CandidateFeatures
    breakdown: ScoreBreakdown
    exploration: bool = False
    rerank_reason: Optional[str] = None

    @property
    def product_id(self) -> str:
        return self.features.product_id

    @property
    def score(self) -> float:
        return self.breakdown.total
