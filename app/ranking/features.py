"""Feature assembly for the ranker (Wave F2) — the DB-bound layer.

Turns Postgres rows into the pure :class:`CandidateFeatures` the scorer consumes. This is
the ONLY ranker module that touches a Session; the math lives in score.py / centroids.py /
rerank.py. It reads item/product embeddings, the user_wardrobe_gap rows, style_events (for
fatigue), and budget (facts, or inferred from receipt prices) — and never imports
``app.monetization`` (import-linter wall).

Everything here is $0 API: embeddings are already stored (pgvector), so taste_match is a
cosine over cached vectors — no model call at serve time. Written defensively for the
pgvector-less (sqlite) path: missing embeddings degrade to taste-neutral, never raise.
"""
from __future__ import annotations

import logging
import statistics
from typing import Dict, List, Optional, Sequence, Tuple
from uuid import UUID

import numpy as np
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    ClothingItem,
    ItemEmbedding,
    Product,
    ProductEmbedding,
    StyleEvent,
    StyleProfile,
    UserWardrobeGap,
)
from app.ranking import centroids as C
from app.ranking.types import CandidateFeatures, RankingConfig

logger = logging.getLogger(__name__)

# style_events that count as POSITIVE behavioural evidence (grows α, shrinks γ).
_POSITIVE_EVENTS = ("save", "wishlist_add", "click_out", "outfit_worn", "outfit_accept", "rate_swipe")
# Archetype-slice size: how many recent catalog products define the archetype centroids.
_ARCHETYPE_CATALOG_SAMPLE = 1500


def _vecs_for_items(db: Session, user_id: UUID, *, favorites_only: bool) -> List[np.ndarray]:
    """Item embeddings for a user (optionally only favorited items). Empty on the sqlite
    path or a fresh closet."""
    q = (
        db.query(ItemEmbedding.embedding)
        .join(ClothingItem, ClothingItem.id == ItemEmbedding.item_id)
        .filter(
            ItemEmbedding.user_id == user_id,
            ItemEmbedding.model == settings.EMBEDDING_MODEL,
            ItemEmbedding.version == settings.EMBEDDING_VERSION,
        )
    )
    if favorites_only:
        q = q.filter(ClothingItem.is_favorite.is_(True))
    out: List[np.ndarray] = []
    for (emb,) in q.all():
        if emb is not None:
            out.append(np.asarray(emb, dtype=np.float64))
    return out


def closet_centroid(db: Session, user_id: UUID) -> Optional[np.ndarray]:
    """Mean of the user's item_embeddings — the direction of what they already own."""
    return C.mean_vector(_vecs_for_items(db, user_id, favorites_only=False))


def liked_centroid(db: Session, user_id: UUID) -> Optional[np.ndarray]:
    """Mean of the user's FAVORITED item embeddings — a positive taste signal. (Extending
    this to saved/wishlisted products is a clean follow-up; favorites are the signal we
    have embeddings for today.)"""
    return C.mean_vector(_vecs_for_items(db, user_id, favorites_only=True))


def evidence_count(db: Session, user_id: UUID) -> int:
    """Behavioural evidence = positive style_events + favorited items. Drives the blend
    schedule (α grows, γ shrinks). Cold-start users score ~0 → archetype-only taste."""
    ev = (
        db.query(StyleEvent.id)
        .filter(StyleEvent.user_id == user_id, StyleEvent.event_type.in_(_POSITIVE_EVENTS))
        .count()
    )
    favs = (
        db.query(ClothingItem.id)
        .filter(ClothingItem.user_id == user_id, ClothingItem.is_favorite.is_(True))
        .count()
    )
    return int(ev) + int(favs)


def archetype_scores(db: Session, user_id: UUID) -> Dict[str, float]:
    """User's per-archetype affinity from onboarding taste swipes (preference_signals
    signal_type='taste_swipe', key=archetype). like → +weight, dislike → −. Clamped ≥ 0.
    Empty → uniform prior over all archetypes (a user with no swipes gets the average look)."""
    from app.models import PreferenceSignal  # local import: keeps module load light

    rows = (
        db.query(PreferenceSignal.key, PreferenceSignal.polarity, PreferenceSignal.weight)
        .filter(
            PreferenceSignal.user_id == user_id,
            PreferenceSignal.signal_type == "taste_swipe",
        )
        .all()
    )
    scores: Dict[str, float] = {}
    for key, polarity, weight in rows:
        if not key:
            continue
        w = float(weight) if weight is not None else 1.0
        sign = -1.0 if polarity == "dislike" else 1.0
        scores[key] = scores.get(key, 0.0) + sign * w
    scores = {k: max(0.0, v) for k, v in scores.items() if max(0.0, v) > 0}
    if not scores:
        return {k: 1.0 for k in C.ARCHETYPE_KEYS}
    return scores


# Process-level cache for the GLOBAL (not per-user) archetype centroids. Built once from a
# catalog slice; a Session can't live in lru_cache, so cache the computed vectors here.
_ARCH_CACHE: Dict[str, object] = {}


def archetype_centroid_map(db: Session) -> Tuple[Dict[str, np.ndarray], Optional[np.ndarray]]:
    """{archetype → centroid} (product-derived) + the global product centroid fallback.

    Global (not per-user), so computed once per process from a recent catalog slice and
    cached — $0 API (pure pgvector reads + numpy mean). Recomputed only on cache miss."""
    if "map" in _ARCH_CACHE:
        return _ARCH_CACHE["map"], _ARCH_CACHE.get("global")  # type: ignore[return-value]

    products = (
        db.query(Product)
        .filter(Product.active.is_(True))
        .order_by(Product.last_seen_at.desc())
        .limit(_ARCHETYPE_CATALOG_SAMPLE)
        .all()
    )
    pids = [p.id for p in products]
    emb_by_id: Dict[str, Sequence[float]] = {}
    if pids:
        for pid, emb in (
            db.query(ProductEmbedding.product_id, ProductEmbedding.embedding)
            .filter(
                ProductEmbedding.product_id.in_(pids),
                ProductEmbedding.model == settings.EMBEDDING_MODEL,
                ProductEmbedding.version == settings.EMBEDDING_VERSION,
            )
            .all()
        ):
            if emb is not None:
                emb_by_id[str(pid)] = emb

    cmap = C.archetype_centroid_map(products, emb_by_id)
    global_centroid = C.mean_vector(list(emb_by_id.values())) if emb_by_id else None
    _ARCH_CACHE["map"] = cmap
    _ARCH_CACHE["global"] = global_centroid
    return cmap, global_centroid


def archetype_centroid_for_user(db: Session, user_id: UUID) -> Optional[np.ndarray]:
    """The user's archetype prior: their taste-swipe scores blended over the archetype
    centroid map (global product centroid substituting for thin archetypes)."""
    cmap, global_centroid = archetype_centroid_map(db)
    scores = archetype_scores(db, user_id)
    return C.weighted_archetype_centroid(scores, cmap, fallback=global_centroid)


def taste_blend(db: Session, user_id: UUID, cfg: RankingConfig) -> Optional[np.ndarray]:
    """Assemble the evidence-weighted taste vector for a user (the thing product cosines are
    scored against). Cold-start → archetype prior; warm → liked ⊕ closet dominated."""
    return C.blend_centroid(
        liked_centroid(db, user_id),
        closet_centroid(db, user_id),
        archetype_centroid_for_user(db, user_id),
        evidence_count=evidence_count(db, user_id),
        cfg=cfg,
    )


def inferred_budget_by_category(db: Session, user_id: UUID) -> Dict[str, float]:
    """Cold-start price band: median receipt unit_price per category from the user's own
    purchase history (provenance=inferred). Empty when there are no priced receipts."""
    rows = (
        db.query(ClothingItem.category, ClothingItem.unit_price)
        .filter(
            ClothingItem.user_id == user_id,
            ClothingItem.unit_price.isnot(None),
            ClothingItem.is_return.is_(False),
        )
        .all()
    )
    by_cat: Dict[str, List[float]] = {}
    for cat, price in rows:
        if price is None:
            continue
        by_cat.setdefault((cat or "other"), []).append(float(price))
    return {cat: statistics.median(vals) for cat, vals in by_cat.items() if vals}


def budget_centers(db: Session, user_id: UUID) -> Tuple[Optional[float], Dict[str, float]]:
    """(overall budget center, per-category centers). Prefers facts.budget; falls back to
    inferred receipt medians. Overall center used when a product's category has no band."""
    profile = db.query(StyleProfile).filter(StyleProfile.user_id == user_id).one_or_none()
    facts = dict(profile.facts or {}) if profile is not None else {}
    budget = facts.get("budget") if isinstance(facts.get("budget"), dict) else {}
    per_cat = inferred_budget_by_category(db, user_id)

    overall: Optional[float] = None
    if isinstance(budget, dict):
        for key in ("per_item_usd", "typical_usd", "mid_usd", "monthly_usd"):
            if isinstance(budget.get(key), (int, float)):
                overall = float(budget[key])
                break
        rng = budget.get("range") if isinstance(budget.get("range"), dict) else None
        if overall is None and rng and {"min", "max"} <= set(rng):
            try:
                overall = (float(rng["min"]) + float(rng["max"])) / 2.0
            except (TypeError, ValueError):
                pass
        cat_band = budget.get("by_category")
        if isinstance(cat_band, dict):
            for cat, v in cat_band.items():
                if isinstance(v, (int, float)):
                    per_cat.setdefault(cat, float(v))
    if overall is None and per_cat:
        overall = statistics.median(list(per_cat.values()))
    return overall, per_cat


def impressions_by_product(db: Session, user_id: UUID, product_ids: Sequence[str]) -> Dict[str, int]:
    """Per-product impression counts (fatigue source) from style_events: impression rows
    whose entity_id is the product id. One grouped query."""
    if not product_ids:
        return {}
    rows = (
        db.query(StyleEvent.entity_id)
        .filter(
            StyleEvent.user_id == user_id,
            StyleEvent.event_type == "impression",
            StyleEvent.entity_type == "product",
            StyleEvent.entity_id.in_([str(p) for p in product_ids]),
        )
        .all()
    )
    counts: Dict[str, int] = {}
    for (eid,) in rows:
        if eid:
            counts[str(eid)] = counts.get(str(eid), 0) + 1
    return counts


def _quality_recency(product) -> float:
    """[0,1] product quality signal: verified image present + in stock, lightly boosted by
    freshness (recently re-seen catalog rows are more trustworthy). Interpretable, no I/O."""
    q = 0.5
    if getattr(product, "image_url", None):
        q += 0.3          # a verified image (products.image_url is set only post-verify)
    if getattr(product, "in_stock", None) is True:
        q += 0.2
    elif getattr(product, "in_stock", None) is False:
        q -= 0.3
    return max(0.0, min(1.0, q))


def closet_category_mix(db: Session, user_id: UUID) -> Dict[str, float]:
    """Target category shares for calibration = the user's closet category distribution.
    Empty (cold start) → {} (calibration then a no-op; feed follows pure relevance)."""
    rows = (
        db.query(ClothingItem.category)
        .filter(ClothingItem.user_id == user_id, ClothingItem.archived_at.is_(None))
        .all()
    )
    counts: Dict[str, int] = {}
    for (cat,) in rows:
        c = cat or "other"
        counts[c] = counts.get(c, 0) + 1
    total = sum(counts.values())
    if not total:
        return {}
    return {k: v / total for k, v in counts.items()}


def candidate_features(
    db: Session,
    user_id: UUID,
    blend: Optional[np.ndarray],
    cfg: RankingConfig,
    *,
    limit: int,
) -> List[CandidateFeatures]:
    """Build the ranker's candidate pool for a user.

    Primary source: the user_wardrobe_gap rows the nightly job wrote (they ARE the top-K
    taste candidates, each carrying a precomputed unlock_count + gap_context). Fallback
    (no job has run / cold start): live pgvector top-K by taste. taste_match is recomputed
    at serve time from the stored product embedding — $0 API."""
    gap_rows = (
        db.query(UserWardrobeGap, Product, ProductEmbedding.embedding)
        .join(Product, Product.id == UserWardrobeGap.product_id)
        .outerjoin(
            ProductEmbedding,
            (ProductEmbedding.product_id == Product.id)
            & (ProductEmbedding.model == settings.EMBEDDING_MODEL)
            & (ProductEmbedding.version == settings.EMBEDDING_VERSION),
        )
        .filter(UserWardrobeGap.user_id == user_id, Product.active.is_(True))
        .order_by(UserWardrobeGap.unlock_count.desc())
        .limit(limit)
        .all()
    )

    rows: List[Tuple[Product, Optional[object], int, dict]] = []
    if gap_rows:
        for gap, product, emb in gap_rows:
            rows.append((product, emb, gap.unlock_count, dict(gap.gap_context or {})))
    else:
        rows = _fallback_taste_candidates(db, blend, limit)

    if not rows:
        return []

    overall_budget, per_cat_budget = budget_centers(db, user_id)
    product_ids = [str(p.id) for p, _e, _u, _g in rows]
    impressions = impressions_by_product(db, user_id, product_ids)

    feats: List[CandidateFeatures] = []
    for product, emb, unlock_count, gap_ctx in rows:
        vec = np.asarray(emb, dtype=np.float64) if emb is not None else None
        taste = C.cosine(blend, C.l2_normalize(vec)) if (blend is not None and vec is not None) else 0.0
        cat = product.category or "other"
        budget_center = per_cat_budget.get(cat, overall_budget)
        feats.append(
            CandidateFeatures(
                product_id=str(product.id),
                taste_match=taste,
                unlock_count=int(unlock_count or 0),
                fills_empty_occasion=bool(gap_ctx.get("fills_empty_l1")),
                price=float(product.price) if product.price is not None else None,
                budget_center=budget_center,
                quality_recency=_quality_recency(product),
                impressions=impressions.get(str(product.id), 0),
                category=cat,
                embedding=tuple(vec.tolist()) if vec is not None else None,
            )
        )
    return feats


def _fallback_taste_candidates(
    db: Session, blend: Optional[np.ndarray], limit: int
) -> List[Tuple[Product, Optional[object], int, dict]]:
    """Cold-start / pre-job candidate pool: live pgvector top-K by cosine to the taste blend
    (unlock_count 0, no gap_context). Degrades to recent active products if no blend/pgvector."""
    if blend is not None:
        try:
            vec = [float(x) for x in np.asarray(blend, dtype=np.float64).tolist()]
            q = (
                db.query(Product, ProductEmbedding.embedding)
                .join(ProductEmbedding, ProductEmbedding.product_id == Product.id)
                .filter(
                    Product.active.is_(True),
                    ProductEmbedding.model == settings.EMBEDDING_MODEL,
                    ProductEmbedding.version == settings.EMBEDDING_VERSION,
                )
                .order_by(ProductEmbedding.embedding.cosine_distance(vec))
                .limit(limit)
            )
            return [(p, e, 0, {}) for p, e in q.all()]
        except Exception:  # pragma: no cover - pgvector-less path
            logger.debug("pgvector taste fallback unavailable; using recent-active products")

    recent = (
        db.query(Product)
        .filter(Product.active.is_(True))
        .order_by(Product.last_seen_at.desc())
        .limit(limit)
        .all()
    )
    return [(p, None, 0, {}) for p in recent]


def top_taste_products(db: Session, blend: Optional[np.ndarray], limit: int) -> List[Product]:
    """The gap job's candidate pool: top-K catalog products by taste_match (pgvector).
    Same source as the feed's cold-start fallback, exposed for the nightly job."""
    return [row[0] for row in _fallback_taste_candidates(db, blend, limit)]
