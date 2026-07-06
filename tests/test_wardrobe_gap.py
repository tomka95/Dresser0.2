"""Marginal-outfit-unlock core (Wave F2). Pure, DB-free — constructs ClothingItem/Product
ORM objects in memory (no Session) and checks that owning a candidate product unlocks the
right number of wardrobe contexts against a closet with a real gap.
"""
from __future__ import annotations

import uuid

from app.models import ClothingItem, Product
from app.ranking.gap import _ProductItem, compute_wardrobe_gaps
from app.ranking.types import RankingConfig
from app.services.stylist.profile import ProfileBlock

CFG = RankingConfig()


def _item(n, name, cat, **kw):
    return ClothingItem(id=uuid.UUID(int=n), user_id=uuid.UUID(int=999), name=name, category=cat, **kw)


def _prod(n, name, cat, **kw):
    return Product(id=uuid.UUID(int=n), source="feed", name=name, product_url="http://x", category=cat, **kw)


# Closet with tops + footwear but NO bottoms → separates contexts are unfillable.
_CLOSET = [
    _item(1, "White Tee", "top", formality=2, warmth=1, color_primary="white", occasions=["casual"]),
    _item(2, "Oxford", "top", formality=3, warmth=1, color_primary="white", occasions=["work"]),
    _item(3, "Sneakers", "footwear", formality=2, color_primary="white"),
    _item(4, "Oxfords", "footwear", formality=4, color_primary="black"),
]


def test_missing_slot_product_unlocks_outfits():
    jeans = _prod(100, "Black Jeans", "bottom", formality=2, color_primary="black", occasions=["casual"])
    slacks = _prod(101, "Wool Slacks", "bottom", formality=4, color_primary="charcoal", occasions=["work"])
    res = {r.product_id: r for r in compute_wardrobe_gaps(_CLOSET, {}, [jeans, slacks], ProfileBlock(), CFG)}

    j = res[str(jeans.id)]
    assert j.unlock_count >= 2                       # a bottom unlocks the empty separates contexts
    assert j.gap_context["categories"] == ["bottom"]
    assert j.gap_context["fills_empty_l1"] is True   # casual/work are L1 occasions
    assert j.gap_context["example_item_ids"]         # owned pieces named for the preview


def test_redundant_slot_unlocks_fewer_than_missing_slot():
    """Marginality is real. In a BOTTOMLESS closet, a bottom unlocks the separates contexts
    while another top unlocks nothing — there is still no bottom to pair it with, so no outfit
    becomes sufficient. (Only required slots — top/bottom/dress/footwear — can flip
    sufficiency; outerwear/accessory are optional and never do.)"""
    redundant_top = _prod(102, "Another Tee", "top", formality=2, color_primary="blue", occasions=["casual"])
    missing_bottom = _prod(103, "Black Jeans", "bottom", formality=2, color_primary="black", occasions=["casual"])

    res = {r.product_id: r for r in
           compute_wardrobe_gaps(_CLOSET, {}, [redundant_top, missing_bottom], ProfileBlock(), CFG)}
    assert res[str(redundant_top.id)].unlock_count == 0
    assert res[str(missing_bottom.id)].unlock_count >= 2
    assert res[str(redundant_top.id)].unlock_count < res[str(missing_bottom.id)].unlock_count


def test_product_adapter_exposes_assembler_fields():
    p = _prod(1, "Linen Shirt", "top", formality=2, warmth=1, color_primary="beige",
              color_primary_hex="#eaddc0", material="linen", occasions=["brunch"])
    a = _ProductItem(p)
    assert a.category == "top" and a.material == "linen" and a.formality == 2
    assert a.is_favorite is False and a.last_worn_at is None   # never-owned defaults
    assert a.id == p.id
