"""Feed assembly for GET /shop (Wave F2) — the orchestrator.

Ties the layers together: taste blend → candidate features → interpretable score →
MMR/calibration/exploration re-rank → mixed cards (≈70% product, ≈30% outfit). Paginated by
a session watermark (a stable seed + integer cursor) so pages of one session are consistent
and reproducible. Cold-start (a near-empty closet) drops outfit cards and frames the feed as
archetype "starter looks".

No monetization import: cards carry a productId, never an outbound URL — the client mints the
click via POST /clicks and follows /out/{click_id} (app/monetization owns that redirect).
"""
from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Product
from app.ranking import features as F
from app.ranking import rerank as R
from app.ranking import score as S
from app.ranking.contexts import CONTEXT_GRID
from app.ranking.types import RankingConfig, ScoredCandidate
from app.services.stylist.composer import compose_outfit
from app.services.stylist.profile import assemble_profile

logger = logging.getLogger(__name__)

_CTX_BY_LABEL = {c.label: c for c in CONTEXT_GRID}


@dataclass
class FeedPage:
    cards: List[dict]
    cursor: int                     # offset of the NEXT page (echo back to paginate)
    session_id: str                 # the watermark; the client echoes it for a stable feed
    has_more: bool
    framing: str                    # "personalized" | "starter_looks" (cold start)
    total_ranked: int = 0
    diagnostics: dict = field(default_factory=dict)


def _seed_from_session(session_id: str) -> int:
    """Stable 32-bit seed from the session watermark (deterministic pagination — no clock)."""
    return int(hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:8], 16)


def _product_public(product: Product) -> dict:
    """The safe, wire-facing product fields. NO outbound/affiliate URL — clicks go through
    POST /clicks by productId."""
    return {
        "productId": str(product.id),
        "name": product.name,
        "brand": product.brand,
        "merchant": product.merchant,
        "imageUrl": product.image_url,
        "price": float(product.price) if product.price is not None else None,
        "currency": product.currency,
        "category": product.category,
    }


def build_feed(
    db: Session,
    user_id: UUID,
    *,
    session_id: str,
    cursor: int = 0,
    page_size: Optional[int] = None,
    cfg: Optional[RankingConfig] = None,
) -> FeedPage:
    cfg = cfg or RankingConfig.from_settings(settings)
    page_size = page_size or cfg.feed_page_size

    profile = assemble_profile(db, user_id)
    closet_mix = F.closet_category_mix(db, user_id)
    closet_size = _closet_count(db, user_id)
    cold_start = closet_size < cfg.outfit_min_closet

    blend = F.taste_blend(db, user_id, cfg)
    feats = F.candidate_features(db, user_id, blend, cfg, limit=cfg.gap_candidate_k)
    scored = S.score_all(feats, cfg)

    seed = _seed_from_session(session_id)
    # Rank the WHOLE pool once (deterministic given seed); paginate by slicing.
    ranked = R.rerank(scored, cfg, target_mix=closet_mix, seed=seed, limit=len(scored))

    window = ranked[cursor: cursor + page_size]
    has_more = cursor + page_size < len(ranked)

    # Resolve product rows for the window in one query.
    prod_ids = [c.product_id for c in window]
    products = _load_products(db, prod_ids)

    cards = _build_cards(
        db, user_id, profile, window, products, cfg,
        cold_start=cold_start, start_position=cursor,
    )

    return FeedPage(
        cards=cards,
        cursor=cursor + page_size,
        session_id=session_id,
        has_more=has_more,
        framing="starter_looks" if cold_start else "personalized",
        total_ranked=len(ranked),
        diagnostics={
            "closet_size": closet_size,
            "candidates": len(feats),
            "blend_available": blend is not None,
            "exploration_positions": sum(1 for c in window if c.exploration),
        },
    )


def _closet_count(db: Session, user_id: UUID) -> int:
    from app.models import ClothingItem
    return (
        db.query(ClothingItem.id)
        .filter(ClothingItem.user_id == user_id, ClothingItem.archived_at.is_(None))
        .count()
    )


def _load_products(db: Session, product_ids: List[str]) -> Dict[str, Product]:
    if not product_ids:
        return {}
    rows = db.query(Product).filter(Product.id.in_(product_ids)).all()
    return {str(p.id): p for p in rows}


def _build_cards(
    db: Session,
    user_id: UUID,
    profile,
    window: List[ScoredCandidate],
    products: Dict[str, Product],
    cfg: RankingConfig,
    *,
    cold_start: bool,
    start_position: int,
) -> List[dict]:
    """Interleave product (~70%) and outfit (~30%) cards. Outfit cards are skipped on cold
    start (nothing to compose against). ``feed_position`` is absolute (survives pagination)
    so impression events sort globally."""
    # Which window positions become outfit cards (evenly spaced, ~ratio of them).
    outfit_slots: set = set()
    if not cold_start and cfg.outfit_card_ratio > 0:
        step = max(1, round(1.0 / cfg.outfit_card_ratio))
        outfit_slots = {i for i in range(len(window)) if i % step == step - 1}

    cards: List[dict] = []
    for i, cand in enumerate(window):
        product = products.get(cand.product_id)
        if product is None:
            continue
        position = start_position + i
        if i in outfit_slots and cand.features.unlock_count > 0:
            card = _outfit_card(db, user_id, profile, cand, product, cfg)
            if card is not None:
                card.update(_common_fields(cand, position, "outfit"))
                cards.append(card)
                continue
        # default: product card
        card = _product_card(cand, product, cold_start)
        card.update(_common_fields(cand, position, "product"))
        cards.append(card)
    return cards


def _common_fields(cand: ScoredCandidate, position: int, card_type: str) -> dict:
    """Fields every card carries for the client's event capture — feed_position, card_type,
    the exploration flag (echoed into the impression event), and the score for debugging."""
    return {
        "feedPosition": position,
        "cardType": card_type,
        "exploration": cand.exploration,
        "score": round(cand.score, 4),
    }


def _product_card(cand: ScoredCandidate, product: Product, cold_start: bool) -> dict:
    n = cand.features.unlock_count
    if cold_start:
        headline = "A starter piece for your style"
    elif n > 0:
        headline = f"Unlocks {n} new outfit{'s' if n != 1 else ''} with your closet"
    else:
        headline = "Matches your taste"
    return {
        "type": "product",
        "product": _product_public(product),
        "unlockCount": n,
        "headline": headline,
        "gapContext": _public_gap_context(cand),
    }


def _public_gap_context(cand: ScoredCandidate) -> dict:
    # The preview payload the expand sheet renders. example_item_ids drive the "goes with"
    # thumbnails. Sourced from the stored gap_context (features don't carry it; the feed
    # re-derives the light fields it needs from unlock_count/fills_empty_occasion).
    return {
        "fillsEmptyOccasion": cand.features.fills_empty_occasion,
        "category": cand.features.category,
    }


def _outfit_card(
    db: Session,
    user_id: UUID,
    profile,
    cand: ScoredCandidate,
    product: Product,
    cfg: RankingConfig,
) -> Optional[dict]:
    """An owned-outfit + 1-buyable card: compose an owned look for an occasion the product
    helps unlock, attach the product as the buyable that completes it, and (best-effort)
    render the owned items into a PIL collage (reuse collage.py). Returns None if nothing
    composable — the caller falls back to a product card."""
    ctx = _pick_context(product)
    try:
        outfit = compose_outfit(
            db, user_id, profile,
            occasion=ctx.occasion,
            formality_target=ctx.formality,
            warmth_target=ctx.warmth,
        )
    except Exception:  # pragma: no cover - never let one card 500 the feed
        logger.debug("compose_outfit failed for outfit card", exc_info=True)
        return None

    owned_slots = {slot: item for slot, item in outfit.slots.items()}
    if len(owned_slots) < 2:
        return None  # not enough owned pieces to frame a look

    collage_url = None
    try:
        from app.services.stylist.collage import get_or_create_outfit_collage
        collage_url = get_or_create_outfit_collage(user_id, owned_slots, ctx.occasion)
    except Exception:  # pragma: no cover
        logger.debug("collage render failed for outfit card", exc_info=True)

    return {
        "type": "outfit",
        "occasion": ctx.occasion,
        "ownedItemIds": [str(it.id) for it in owned_slots.values()],
        "buyable": _product_public(product),
        "buyableProductId": str(product.id),
        "unlockCount": cand.features.unlock_count,
        "collageUrl": collage_url,
        "rationale": (outfit.rationale or "").strip()
        or f"Completes a {ctx.occasion or 'daily'} look with what you own.",
    }


def _pick_context(product: Product):
    """Choose the context an outfit card composes for: a product occasion that maps into the
    grid, else the closest-formality grid context."""
    occs = {str(o).lower() for o in (product.occasions or [])}
    for c in CONTEXT_GRID:
        if c.occasion and c.occasion in occs:
            return c
    if product.formality is not None:
        return min(CONTEXT_GRID, key=lambda c: abs(c.formality - int(product.formality)))
    return CONTEXT_GRID[0]
