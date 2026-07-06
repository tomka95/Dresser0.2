"""Golden behaviour lock for compose_outfit (F1a assembler lift).

Captures compose_outfit's full output (slots, score, confidence, sufficient,
gaps, warnings, rationale) over a deterministic wardrobe across a matrix of
scenarios, and asserts it byte-identical against a committed snapshot. This is
the correctness gate for lifting the greedy assembler into a pure
``assemble_from_pool``: the refactor is only done when this stays green.

Determinism: item ids are FIXED (uuid int), no ``last_worn_at`` is set (its
rotation penalty reads wall-clock), so both the tie-break (``_pick`` sorts on
``str(item.id)``) and every score are reproducible run-to-run.

Record mode: delete tests/golden/composer_golden.json (or set
RECORD_COMPOSER_GOLDEN=1) and run once to regenerate the snapshot from the
CURRENT composer, then re-run to assert. The snapshot committed here was
recorded against the pre-refactor composer.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db import Base, engine, SessionLocal
from app.models import ClothingItem, User
from app.services.stylist.composer import compose_outfit
from app.services.stylist.profile import ProfileBlock

GOLDEN_PATH = Path(__file__).parent / "golden" / "composer_golden.json"


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _uid(n: int) -> uuid.UUID:
    return uuid.UUID(int=n)


# (id, name, category, kwargs) — fixed ids for deterministic tie-breaks.
_WARDROBE = [
    (1, "White Tee", "top", dict(formality=1, warmth=1, color_primary="white", occasions=["casual"])),
    (2, "Oxford Shirt", "top", dict(formality=3, warmth=1, color_primary="white", color_primary_hex="#f0f0f0", occasions=["work"])),
    (3, "Neon Hoodie", "top", dict(formality=1, warmth=2, color_primary="neon green", color_primary_hex="#39ff14", occasions=["casual"])),
    (4, "Nike Running Tank", "top", dict(formality=1, color_primary="black", material="polyester", occasions=["athletic", "gym"])),
    (5, "Black Jeans", "bottom", dict(formality=2, color_primary="black", occasions=["casual"])),
    (6, "Wool Slacks", "bottom", dict(formality=4, color_primary="charcoal", occasions=["work"])),
    (7, "Athletic Shorts", "bottom", dict(formality=1, color_primary="black", material="polyester", occasions=["gym"])),
    (8, "Leather Sneakers", "footwear", dict(formality=2, color_primary="white")),
    (9, "Oxford Shoes", "footwear", dict(formality=4, color_primary="black")),
    (10, "Running Sneakers", "footwear", dict(formality=1, color_primary="white", occasions=["gym"])),
    (11, "Down Parka", "outerwear", dict(formality=1, warmth=3, color_primary="navy")),
    (12, "Grey Blazer", "outerwear", dict(formality=4, warmth=2, color_primary="grey")),
    (13, "Silk Dress", "dress", dict(formality=4, color_primary="red", color_primary_hex="#c01020", occasions=["evening"])),
    (14, "Leather Belt", "accessory", dict(formality=3, color_primary="brown")),
    (15, "Blue Chinos", "bottom", dict(formality=2, color_primary="blue", color_primary_hex="#2040c0", occasions=["casual"])),
]

_NAME_BY_ID = {str(_uid(i)): name for i, name, _c, _k in _WARDROBE}


def _seed(db: Session) -> User:
    u = User(id=_uid(1000), email="golden@example.com", hashed_password="x")
    db.add(u)
    db.commit()
    for iid, name, category, kw in _WARDROBE:
        db.add(ClothingItem(id=_uid(iid), user_id=u.id, name=name, category=category, **kw))
    db.commit()
    return u


# Each scenario: label -> (compose kwargs, ProfileBlock).
def _scenarios(uid: uuid.UUID):
    return {
        "formal_4": (dict(formality_target=4), ProfileBlock()),
        "casual_1": (dict(formality_target=1), ProfileBlock()),
        "cold_outerwear": (dict(formality_target=1, warmth_target=3), ProfileBlock()),
        "hot_no_outerwear": (dict(formality_target=1, warmth_target=1), ProfileBlock()),
        "dinner_2": (dict(occasion="dinner", formality_target=2), ProfileBlock()),
        "gym_1": (dict(occasion="gym", formality_target=1), ProfileBlock()),
        "evening_4": (dict(occasion="evening", formality_target=4), ProfileBlock()),
        "anchor_jeans": (dict(formality_target=2, anchor_item_ids=[_uid(5)]), ProfileBlock()),
        # Two anchors in the SAME slot: one places, the other is unplaceable — the
        # exact edge where the lift's anchor-exclusion differs from the original.
        "anchor_two_tops": (dict(formality_target=2, anchor_item_ids=[_uid(1), _uid(2)]), ProfileBlock()),
        # Dress anchor forces the dress route.
        "anchor_dress": (dict(occasion="evening", formality_target=4, anchor_item_ids=[_uid(13)]), ProfileBlock()),
        "avoid_neon": (dict(formality_target=1), ProfileBlock(hard_avoids=["neon green"])),
        "exclude_sneakers": (dict(formality_target=2, exclude_item_ids=[_uid(8), _uid(10)]), ProfileBlock()),
        "prefer_white": (
            dict(formality_target=2),
            ProfileBlock(preferences=[{"dimension": "color", "value": "white", "polarity": "like", "confidence": 0.9}]),
        ),
        "work_3": (dict(occasion="work", formality_target=3), ProfileBlock()),
    }


def _snapshot(outfit) -> dict:
    payload = outfit.to_payload()
    return {
        "slots": {slot: _NAME_BY_ID[str(item.id)] for slot, item in outfit.slots.items()},
        "itemIds": payload["itemIds"],
        "score": round(outfit.score, 6),
        "sufficient": payload["sufficient"],
        "confidence": payload["confidence"],
        "gaps": payload["gaps"],
        "warnings": payload["warnings"],
        "rationale": payload["rationale"],
    }


def _compute(db: Session) -> dict:
    u = _seed(db)
    out = {}
    for label, (kwargs, profile) in _scenarios(u.id).items():
        outfit = compose_outfit(db, u.id, profile, **kwargs)
        out[label] = _snapshot(outfit)
    return out


def test_compose_outfit_matches_golden(db):
    result = _compute(db)

    record = os.environ.get("RECORD_COMPOSER_GOLDEN") == "1" or not GOLDEN_PATH.exists()
    if record:
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        pytest.skip(f"recorded golden -> {GOLDEN_PATH} ({len(result)} scenarios)")

    golden = json.loads(GOLDEN_PATH.read_text())
    # Per-scenario diff for a readable failure.
    mismatches = [k for k in golden if result.get(k) != golden[k]]
    assert not mismatches, "composer output drifted for: " + ", ".join(mismatches) + (
        "\n" + json.dumps({k: {"golden": golden[k], "got": result.get(k)} for k in mismatches}, indent=2)
    )
    assert set(result) == set(golden), "scenario set changed"
