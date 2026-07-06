"""F1a: assemble_from_pool is pure (no DB / LLM / I/O) and behaviour-matches the
composer's assembly. Imported via the batch-facing compat seam.
"""
from __future__ import annotations

import inspect
import uuid

from app.models import ClothingItem
from app.services.stylist import compat
from app.services.stylist.profile import ProfileBlock


def _item(n, name, category, **kw) -> ClothingItem:
    # Detached ORM objects — never added to a session. Fixed ids for determinism.
    return ClothingItem(id=uuid.UUID(int=n), user_id=uuid.UUID(int=999),
                        name=name, category=category, **kw)


def _closet():
    return [
        _item(1, "White Tee", "top", formality=1, color_primary="white"),
        _item(2, "Oxford Shirt", "top", formality=3, color_primary="white"),
        _item(3, "Black Jeans", "bottom", formality=2, color_primary="black"),
        _item(4, "Wool Slacks", "bottom", formality=4, color_primary="charcoal"),
        _item(5, "Leather Sneakers", "footwear", formality=2, color_primary="white"),
        _item(6, "Oxford Shoes", "footwear", formality=4, color_primary="black"),
        _item(7, "Grey Blazer", "outerwear", formality=4, warmth=2, color_primary="grey"),
    ]


def test_assemble_from_pool_is_pure_no_db_no_llm():
    """The pure assembler runs on detached objects with no Session anywhere, and
    its source references no db / provider / network symbols."""
    outfit = compat.assemble_from_pool(
        _closet(), formality_target=4, profile=ProfileBlock()
    )
    # formality 4 ±1 -> shirt(3)/slacks(4)/oxford(4), blazer added (formal).
    assert outfit.slots["top"].name == "Oxford Shirt"
    assert outfit.slots["bottom"].name == "Wool Slacks"
    assert outfit.slots["footwear"].name == "Oxford Shoes"
    assert outfit.sufficient is True

    src = inspect.getsource(compat.assemble_from_pool)
    for forbidden in ("Session", "db.", "get_ai_provider", "httpx", "search_closet_items", "get_owned_items"):
        assert forbidden not in src, f"pure assembler leaked a dependency: {forbidden}"


def test_assemble_from_pool_hard_avoid_and_gap():
    closet = _closet() + [_item(8, "Neon Cap", "accessory", color_primary="neon green")]
    outfit = compat.assemble_from_pool(
        closet, formality_target=4, profile=ProfileBlock(hard_avoids=["neon green"])
    )
    assert "Neon Cap" not in {i.name for i in outfit.slots.values()}

    # A closet missing a required slot is honestly reported, not force-filled.
    tops_only = [_item(1, "White Tee", "top", formality=1)]
    partial = compat.assemble_from_pool(tops_only, formality_target=1, profile=ProfileBlock())
    assert partial.sufficient is False
    assert "bottom" in partial.gaps and "footwear" in partial.gaps


def test_compat_reexports_predicates():
    a = _item(1, "a", "top", color_primary="black")
    b = _item(2, "b", "top", color_primary="red", color_primary_hex="#e01010")
    assert compat.color_harmony(a, b) == 0.5              # neutral pairs safely
    assert compat.violates_hard_constraints(b, ["red"]) is True
    assert compat.occasion_family("hit the gym") == "athletic"
    assert compat.formality_ok(_item(1, "x", "top", formality=3), 4) is True
