"""Marginal-outfit-unlock: the wardrobe-gap computation core (Wave F2).

Pure CPU, $0 API. Reuses ``assemble_from_pool`` (app.services.stylist.compat) — the exact
rule engine the chat stylist composes with — to answer, per candidate product: how many of
the fixed :data:`CONTEXT_GRID` contexts does owning it NEWLY let the user dress for, given
what they already own?

Algorithm (per user):
  1. Cap combinatorics: bucket the closet by slot and keep the top-M embedding-DIVERSE
     representatives per slot (farthest-point sampling). A 200-item closet collapses to
     ≤ M·|slots| assembly inputs, so the grid×candidate fan-out stays bounded.
  2. Baseline: assemble each context over the capped closet ALONE → is it sufficient?
  3. Per candidate: wrap the product as a ClothingItem-shaped adapter, append it to the
     pool, re-assemble the contexts the baseline could NOT satisfy. A context is UNLOCKED
     when it flips insufficient→sufficient AND the candidate is actually placed in the
     winning outfit (a product that doesn't get used unlocked nothing).

``unlock_count`` = number of unlocked contexts; ``gap_context`` carries the preview payload
(occasions/categories filled + example owned-item ids). No DB here — the dev job loads/writes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence
from uuid import UUID

import numpy as np

from app.ranking.contexts import CONTEXT_GRID, WardrobeContext
from app.ranking.types import RankingConfig
from app.services.enrichment import normalize_category
from app.services.stylist.compat import SLOT_CATEGORIES, assemble_from_pool
from app.services.stylist.profile import ProfileBlock


@dataclass
class GapResult:
    product_id: str
    unlock_count: int
    gap_context: dict


class _ProductItem:
    """A ClothingItem-shaped view of a catalog product for ``assemble_from_pool``.

    The assembler reads plain attributes (category / formality / warmth / occasions / colour
    / material / pattern / name / id / is_favorite / last_worn_at) — never a Session — so a
    lightweight adapter drops a product into the exact same rule path as an owned item. ``id``
    is the product id (kept as the raw value for the assembler's str(id) tie-break)."""

    __slots__ = (
        "id", "name", "category", "sub_category", "color_primary", "color_primary_hex",
        "color_secondary", "material", "pattern", "fit_silhouette", "formality", "warmth",
        "occasions", "seasons", "is_favorite", "last_worn_at",
    )

    def __init__(self, product):
        self.id = product.id
        self.name = getattr(product, "name", None) or "product"
        self.category = getattr(product, "category", None)
        self.sub_category = getattr(product, "subcategory", None)
        self.color_primary = getattr(product, "color_primary", None)
        self.color_primary_hex = getattr(product, "color_primary_hex", None)
        self.color_secondary = getattr(product, "color_secondary", None)
        self.material = getattr(product, "material", None)
        self.pattern = getattr(product, "pattern", None)
        self.fit_silhouette = getattr(product, "fit_silhouette", None)
        self.formality = getattr(product, "formality", None)
        self.warmth = getattr(product, "warmth", None)
        self.occasions = getattr(product, "occasions", None) or []
        self.seasons = getattr(product, "seasons", None) or []
        self.is_favorite = False        # a not-yet-owned product is never a "favorite"
        self.last_worn_at = None        # never worn → no rotation penalty


def _slot_of(item) -> Optional[str]:
    category = normalize_category(getattr(item, "category", None)) or (getattr(item, "category", None) or "")
    for slot, cats in SLOT_CATEGORIES.items():
        if category in cats:
            return slot
    return None


def _diverse_topm(
    items: Sequence,
    emb_by_id: Dict[str, Sequence[float]],
    m: int,
) -> List:
    """Farthest-point sampling: pick up to ``m`` items whose embeddings are maximally spread,
    so the capped slot keeps distinct styles rather than m near-duplicates. Items without an
    embedding are appended after (deterministic order) if room remains."""
    if len(items) <= m:
        return list(items)
    with_emb = [(it, np.asarray(emb_by_id[str(it.id)], dtype=np.float64))
                for it in items if str(it.id) in emb_by_id]
    without = [it for it in items if str(it.id) not in emb_by_id]
    if not with_emb:
        # No embeddings (e.g. sqlite path): deterministic id-sorted head.
        return sorted(items, key=lambda it: str(it.id))[:m]

    # Seed with the two most distant, then greedily add the farthest-from-selected.
    chosen: List = [with_emb[0]]
    pool = with_emb[1:]
    while pool and len(chosen) < m:
        best_i, best_d = 0, -1.0
        for i, (_it, v) in enumerate(pool):
            d = min(float(np.linalg.norm(v - cv)) for _c, cv in chosen)
            if d > best_d:
                best_d, best_i = d, i
        chosen.append(pool.pop(best_i))
    out = [it for it, _v in chosen]
    if len(out) < m:
        out.extend(without[: m - len(out)])
    return out


def cap_closet(
    closet_items: Sequence,
    emb_by_id: Dict[str, Sequence[float]],
    m: int,
) -> List:
    """Reduce the closet to ≤ m embedding-diverse representatives PER SLOT (combinatorics
    cap). Items outside the recognised slots are dropped (they can't fill an outfit slot)."""
    by_slot: Dict[str, List] = {}
    for it in closet_items:
        slot = _slot_of(it)
        if slot is None:
            continue
        by_slot.setdefault(slot, []).append(it)
    capped: List = []
    for slot, items in by_slot.items():
        capped.extend(_diverse_topm(items, emb_by_id, m))
    return capped


def _context_sufficient(pool: List, profile: ProfileBlock, ctx: WardrobeContext):
    outfit = assemble_from_pool(
        pool,
        formality_target=ctx.formality,
        warmth_target=ctx.warmth,
        occasion=ctx.occasion,
        profile=profile,
    )
    return outfit


def compute_wardrobe_gaps(
    closet_items: Sequence,
    closet_emb_by_id: Dict[str, Sequence[float]],
    candidates: Sequence,
    profile: ProfileBlock,
    cfg: RankingConfig,
    *,
    contexts: Sequence[WardrobeContext] = tuple(CONTEXT_GRID),
) -> List[GapResult]:
    """Per-candidate marginal unlock over the context grid. Returns one GapResult per
    candidate (unlock_count 0 kept — a zero is a real, writable signal)."""
    pool = cap_closet(closet_items, closet_emb_by_id, cfg.gap_slot_top_m)

    # Baseline sufficiency per context over the closet alone.
    baseline: Dict[str, bool] = {}
    for ctx in contexts:
        baseline[ctx.label] = _context_sufficient(pool, profile, ctx).sufficient

    results: List[GapResult] = []
    for product in candidates:
        adapter = _ProductItem(product)
        slot = _slot_of(adapter)
        with_pool = pool + [adapter]
        unlocked_labels: List[str] = []
        unlocked_occasions: List[str] = []
        example_item_ids: List[str] = []
        for ctx in contexts:
            if baseline[ctx.label]:
                continue  # already coverable — the product can't *newly* unlock it
            outfit = _context_sufficient(with_pool, profile, ctx)
            placed = any(getattr(v, "id", None) == adapter.id for v in outfit.slots.values())
            if outfit.sufficient and placed:
                unlocked_labels.append(ctx.label)
                if ctx.occasion:
                    unlocked_occasions.append(ctx.occasion)
                # Example owned items in this unlocked outfit (for the preview sheet).
                for v in outfit.slots.values():
                    vid = str(getattr(v, "id", ""))
                    if vid and vid != str(adapter.id) and vid not in example_item_ids:
                        example_item_ids.append(vid)

        fills_empty_l1 = any(
            c.l1 for c in contexts if c.label in unlocked_labels
        )
        gap_context = {
            "occasions": sorted(set(unlocked_occasions)),
            "categories": [slot] if slot else [],
            "contexts": unlocked_labels,
            "example_item_ids": example_item_ids[:6],
            "fills_empty_l1": fills_empty_l1,
        }
        results.append(
            GapResult(
                product_id=str(product.id),
                unlock_count=len(unlocked_labels),
                gap_context=gap_context,
            )
        )
    return results
