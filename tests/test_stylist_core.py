"""Wave S2 stylist core: profile assembly, retrieval isolation, composer rules."""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.db import Base, engine, SessionLocal
from app.models import ClothingItem, StylePreference, StyleProfile, User
from app.services.stylist.composer import (
    color_harmony,
    compose_outfit,
    violates_hard_constraints,
)
from app.services.stylist.profile import ProfileBlock, assemble_profile, extract_hard_avoids
from app.services.stylist.retrieval import (
    get_owned_items,
    search_closet_items,
    serialize_item,
)


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def user1(db: Session):
    u = User(email="s2a@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture
def user2(db: Session):
    u = User(email="s2b@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


def _item(db, user, name, category, **kw):
    it = ClothingItem(user_id=user.id, name=name, category=category, **kw)
    db.add(it); db.commit(); db.refresh(it)
    return it


# ---------------------------------------------------------------------------
# Profile assembly
# ---------------------------------------------------------------------------
def test_profile_assembly_reads_facts_prefs_and_avoids(db, user1):
    db.add(StyleProfile(user_id=user1.id, facts={
        "sizes": {"top": "M"},
        "avoid": ["crop top", "neon"],
        "onboarding_completed_at": "2026-07-01T00:00:00Z",
    }))
    db.add(StylePreference(user_id=user1.id, dimension="color_palette",
                           value={"likes": "earth tones"}, polarity="like",
                           confidence=0.6, source="onboarding"))
    db.add(StylePreference(user_id=user1.id, dimension="fit",
                           value={}, polarity="dislike", confidence=0.5,
                           active=False, source="onboarding"))
    db.commit()

    block = assemble_profile(db, user1.id)
    assert block.onboarded is True
    assert block.hard_avoids == ["crop top", "neon"]
    # inactive preferences are excluded
    assert [p["dimension"] for p in block.preferences] == ["color_palette"]

    prompt = block.to_prompt_text()
    assert "HARD CONSTRAINTS" in prompt
    assert "never: crop top" in prompt
    assert "color_palette" in prompt
    # server bookkeeping never leaks into the prompt facts
    assert "onboarding_completed_at" not in prompt


def test_profile_assembly_empty_profile_is_safe(db, user1):
    block = assemble_profile(db, user1.id)
    assert block.hard_avoids == []
    assert "No style profile yet" in block.to_prompt_text()


def test_extract_hard_avoids_handles_nested_shapes():
    avoids = extract_hard_avoids({
        "avoid": ["Leather"],
        "never_wear": "heels",
        "hard_constraints": {"colors": ["neon green"], "note": "shorts"},
    })
    assert avoids == ["leather", "heels", "neon green", "shorts"]


# ---------------------------------------------------------------------------
# Retrieval: isolation + filters (the cross-user CANNOT leak test)
# ---------------------------------------------------------------------------
def test_retrieval_never_returns_other_users_items(db, user1, user2):
    mine = _item(db, user1, "My Tee", "top")
    _item(db, user2, "Their Tee", "top")
    _item(db, user2, "Their Jeans", "bottom")

    items = search_closet_items(db, user1.id)
    assert [i.id for i in items] == [mine.id]

    # user2 sees only their own two
    items2 = search_closet_items(db, user2.id)
    assert {i.name for i in items2} == {"Their Tee", "Their Jeans"}


def test_get_owned_items_drops_foreign_and_unknown_ids(db, user1, user2):
    mine = _item(db, user1, "Mine", "top")
    theirs = _item(db, user2, "Theirs", "top")

    resolved = get_owned_items(db, user1.id, [mine.id, theirs.id, uuid.uuid4()])
    assert [i.id for i in resolved] == [mine.id]  # foreign + unknown ids vanish


def test_structured_filters_formality_band_and_category(db, user1):
    _item(db, user1, "Hoodie", "top", formality=1)
    mid = _item(db, user1, "Oxford Shirt", "top", formality=3)
    unknown = _item(db, user1, "Mystery Top", "top")  # NULL formality passes
    _item(db, user1, "Jeans", "bottom", formality=2)

    items = search_closet_items(db, user1.id, categories=["top"],
                                formality_min=2, formality_max=4)
    assert {i.id for i in items} == {mid.id, unknown.id}


def test_retrieval_folds_legacy_category_aliases(db, user1):
    legacy = _item(db, user1, "Old Sneakers", "shoes")     # legacy alias row
    canonical = _item(db, user1, "New Boots", "footwear")
    items = search_closet_items(db, user1.id, categories=["footwear"])
    assert {i.id for i in items} == {legacy.id, canonical.id}


def test_archived_items_are_never_retrieved(db, user1):
    from datetime import datetime

    _item(db, user1, "Archived", "top", archived_at=datetime.utcnow())
    live = _item(db, user1, "Live", "top")
    items = search_closet_items(db, user1.id)
    assert [i.id for i in items] == [live.id]


def test_serialize_item_exposes_no_user_id():
    it = ClothingItem(id=uuid.uuid4(), user_id=uuid.uuid4(), name="X", category="top")
    payload = serialize_item(it)
    assert "userId" not in payload and "user_id" not in payload


def test_vector_query_construction_filters_both_tables_by_user():
    """The kNN SQL must carry the tenant predicate on clothing_items AND
    item_embeddings (defense-in-depth pairs with RLS)."""
    from app.services.stylist.retrieval import _structured_query, _vector_search  # noqa: F401
    import inspect

    src = inspect.getsource(_vector_search)
    assert "ItemEmbedding.user_id == user_id" in src
    # and the shared base query it composes with:
    base_src = inspect.getsource(_structured_query)
    assert "ClothingItem.user_id == user_id" in base_src


# ---------------------------------------------------------------------------
# Composer rules
# ---------------------------------------------------------------------------
def _wardrobe(db, user):
    return {
        "tee": _item(db, user, "White Tee", "top", formality=1, color_primary="white"),
        "shirt": _item(db, user, "Oxford Shirt", "top", formality=3, color_primary="white"),
        "hoodie": _item(db, user, "Neon Hoodie", "top", formality=1, color_primary="neon green"),
        "jeans": _item(db, user, "Black Jeans", "bottom", formality=2, color_primary="black"),
        "slacks": _item(db, user, "Wool Slacks", "bottom", formality=4, color_primary="charcoal"),
        "sneaker": _item(db, user, "Leather Sneakers", "footwear", formality=2, color_primary="white"),
        "oxford": _item(db, user, "Oxford Shoes", "footwear", formality=4, color_primary="black"),
        "parka": _item(db, user, "Down Parka", "outerwear", formality=1, warmth=3, color_primary="navy"),
        "blazer": _item(db, user, "Grey Blazer", "outerwear", formality=4, warmth=2, color_primary="grey"),
    }


def test_compose_respects_formality_band(db, user1):
    w = _wardrobe(db, user1)
    outfit = compose_outfit(db, user1.id, ProfileBlock(), formality_target=4)
    chosen = {slot: item.id for slot, item in outfit.slots.items()}
    # formality 4 ±1: the tee (1) and hoodie (1) are out; shirt (3) is in-band.
    assert chosen["top"] == w["shirt"].id
    assert chosen["bottom"] == w["slacks"].id
    assert chosen["footwear"] == w["oxford"].id
    for item in outfit.slots.values():
        if item.formality is not None:
            assert abs(item.formality - 4) <= 1


def test_compose_excludes_hard_constrained_items(db, user1):
    _wardrobe(db, user1)
    profile = ProfileBlock(hard_avoids=["neon green"])
    outfit = compose_outfit(db, user1.id, profile, formality_target=1)
    names = {i.name for i in outfit.slots.values()}
    assert "Neon Hoodie" not in names


def test_compose_anchor_is_owned_and_placed(db, user1, user2):
    w = _wardrobe(db, user1)
    theirs = _item(db, user2, "Foreign Jacket", "outerwear", formality=2)

    outfit = compose_outfit(
        db, user1.id, ProfileBlock(),
        formality_target=2,
        anchor_item_ids=[w["jeans"].id, theirs.id],  # foreign id must not resolve
    )
    assert outfit.slots["bottom"].id == w["jeans"].id
    assert all(i.user_id == user1.id for i in outfit.slots.values())


def test_compose_warmth_gates_outerwear_and_filters(db, user1):
    w = _wardrobe(db, user1)
    cold = compose_outfit(db, user1.id, ProfileBlock(), formality_target=1, warmth_target=3)
    assert "outerwear" in cold.slots
    assert cold.slots["outerwear"].id == w["parka"].id  # blazer warmth 2 also ok, parka warmth 3 exact

    hot = compose_outfit(db, user1.id, ProfileBlock(), formality_target=1, warmth_target=1)
    assert "outerwear" not in hot.slots


def test_compose_reports_gap_when_slot_empty(db, user1):
    _item(db, user1, "Only Tee", "top", formality=1)
    outfit = compose_outfit(db, user1.id, ProfileBlock(), formality_target=1)
    assert any("bottom" in w for w in outfit.warnings)
    assert any("footwear" in w for w in outfit.warnings)


def test_compose_rationale_is_stored_text(db, user1):
    _wardrobe(db, user1)
    outfit = compose_outfit(db, user1.id, ProfileBlock(), formality_target=2,
                            occasion="dinner")
    payload = outfit.to_payload()
    assert payload["rationale"].startswith("Built for dinner.")
    assert payload["itemIds"]


def test_hard_constraint_matching_is_word_level():
    it = ClothingItem(user_id=uuid.uuid4(), name="Silk Skirt", category="bottom",
                      sub_category="skirt_midi", color_primary="red")
    assert violates_hard_constraints(it, ["skirts"]) is True     # plural tolerated
    assert violates_hard_constraints(it, ["red"]) is True
    assert violates_hard_constraints(it, ["bordeaux"]) is False  # no substring leak


def test_color_harmony_neutrals_and_clash():
    a = ClothingItem(user_id=uuid.uuid4(), name="a", color_primary="black")
    b = ClothingItem(user_id=uuid.uuid4(), name="b", color_primary="red",
                     color_primary_hex="#e01010")
    c = ClothingItem(user_id=uuid.uuid4(), name="c", color_primary="green",
                     color_primary_hex="#10c010")
    assert color_harmony(a, b) == 0.5          # neutral pairs with anything
    assert color_harmony(b, c) < 0             # red/green: saturated mid-distance clash


# ---------------------------------------------------------------------------
# Occasion-family quality gate: never force-fill a gym request with clashing items
# ---------------------------------------------------------------------------
def test_gym_request_refuses_to_force_fill_non_athletic_closet(db, user1):
    # The reported failure case: a closet with nothing athletic.
    _item(db, user1, "Ballet Flats", "footwear", formality=3, color_primary="black")
    _item(db, user1, "Wide-Leg Jeans", "bottom", formality=2, color_primary="blue")
    _item(db, user1, "Yankees Cap", "accessory", formality=1, color_primary="navy")
    _item(db, user1, "Plain Tee", "top", formality=1, color_primary="white")

    outfit = compose_outfit(db, user1.id, ProfileBlock(), occasion="gym", formality_target=1)
    names = {i.name for i in outfit.slots.values()}

    # None of the inappropriate items may be jammed into the outfit.
    assert "Ballet Flats" not in names          # non-athletic footwear rejected
    assert "Wide-Leg Jeans" not in names        # not activewear
    assert "Yankees Cap" not in names           # not activewear
    # The closet genuinely lacks gym pieces -> honest signal, not a forced look.
    assert outfit.sufficient is False
    assert "bottom" in outfit.gaps and "footwear" in outfit.gaps
    payload = outfit.to_payload()
    assert payload["sufficient"] is False
    assert payload["confidence"] < 0.6
    assert any("gym" in w for w in payload["warnings"])


def test_gym_request_composes_from_activewear(db, user1):
    _item(db, user1, "Nike Running Tank", "top", formality=1, color_primary="black")
    _item(db, user1, "Athletic Shorts", "bottom", formality=1, color_primary="black",
          material="polyester")
    _item(db, user1, "Running Sneakers", "footwear", formality=1, color_primary="white")
    # A decoy non-athletic item that must be ignored for a gym request.
    _item(db, user1, "Dress Loafers", "footwear", formality=4, color_primary="brown")

    outfit = compose_outfit(db, user1.id, ProfileBlock(), occasion="gym", formality_target=1)
    names = {i.name for i in outfit.slots.values()}

    assert outfit.sufficient is True
    assert outfit.slots["footwear"].name == "Running Sneakers"  # not the loafers
    assert "Dress Loafers" not in names
    assert {"top", "bottom", "footwear"} <= set(outfit.slots)


def test_athletic_footwear_gate_rejects_non_athletic_shoes():
    from app.services.stylist.composer import _is_athletic_item, occasion_family

    assert occasion_family("hit the gym") == "athletic"
    assert occasion_family("running errands") == "athletic"   # 'running' term (acceptable over-trigger)
    assert occasion_family("dinner") is None

    flats = ClothingItem(user_id=uuid.uuid4(), name="Ballet Flats", category="footwear")
    trainers = ClothingItem(user_id=uuid.uuid4(), name="Running Trainers", category="footwear",
                            sub_category="sneakers")
    assert _is_athletic_item(flats, "footwear") is False
    assert _is_athletic_item(trainers, "footwear") is True
