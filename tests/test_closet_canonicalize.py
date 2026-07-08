"""Phase A: the ONE closet canonicalization chokepoint (Fix 2+3).

Covers the intake invariants: category is never null, size defaults from the user's
onboarding sizes by category (incl. the footwear->shoe key), name is never blank / never a
bare category, provided values are never overwritten (fills empties only), the common case
makes ZERO LLM calls, and canonicalize is idempotent. Plus a DB-backed manual-create test
proving the writer wiring.
"""
import uuid

import pytest
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, engine
from app.models import ClothingItem, StyleProfile, User
from app.services.closet_canonicalize import (
    CanonFields,
    canonicalize_fields,
    default_size_for_category,
)
from app.services.closet_service import create_closet_item


# ---------------------------------------------------------------------------
# Test doubles for the injected LLM provider
# ---------------------------------------------------------------------------
class _Resp:
    def __init__(self, text):
        self.parsed = None
        self.text = text


class _FakeProvider:
    """Returns a fixed structured JSON for the one escalation call."""
    def __init__(self, *, category=None, name=None):
        self.calls = 0
        self._category = category
        self._name = name

    def generate_structured(self, **kw):
        self.calls += 1
        import json

        return _Resp(json.dumps({"category": self._category, "name": self._name}))


class _ExplodingProvider:
    """Fails if the LLM is ever reached — proves the common path is LLM-free."""
    def generate_structured(self, **kw):
        raise AssertionError("LLM must not be called in the common (rules-resolvable) case")


_FACTS = {
    "sizes": {
        "top": "M",
        "bottom": {"system": "waist_inseam", "waist": 32, "inseam": 30},
        "shoe": {"system": "US", "value": "10"},
        "dress": "8",
        "outerwear": "L",
    }
}


# ---------------------------------------------------------------------------
# CATEGORY — never null
# ---------------------------------------------------------------------------
def test_category_never_null_without_llm():
    r = canonicalize_fields(
        CanonFields(name="mystery object zzz", category=None),
        {}, run_llm=False,
    )
    assert r.category == "other"
    assert r.category is not None
    assert r.attributes["category"]["provenance"] == "default"
    assert not r.used_llm


@pytest.mark.parametrize("name,expected", [
    ("Slim Fit Blue Jeans", "bottom"),
    ("Leather Ankle Boot", "footwear"),
    ("Navy Wool Blazer", "outerwear"),
    ("Floral Midi Dress", "dress"),
    ("Cotton Polo Shirt", "top"),
    ("Canvas Tote Bag", "bag"),
    ("Gold Chain Necklace", "jewelry"),
])
def test_category_inferred_from_name_rules_no_llm(name, expected):
    r = canonicalize_fields(CanonFields(name=name, category=None), {},
                            provider=_ExplodingProvider())
    assert r.category == expected
    assert r.attributes["category"]["provenance"] == "inferred"
    assert not r.used_llm


def test_provided_category_kept_and_normalized():
    # legacy alias folds to canonical; a real value is kept with the source provenance.
    r = canonicalize_fields(CanonFields(name="Runners", category="shoes"), {},
                            provider=_ExplodingProvider(), source_provenance="extracted")
    assert r.category == "footwear"
    assert r.attributes["category"]["provenance"] == "extracted"
    r2 = canonicalize_fields(CanonFields(name="Tee", category="top"), {},
                             provider=_ExplodingProvider())
    assert r2.category == "top"


def test_category_llm_escalation_when_rules_fail():
    fake = _FakeProvider(category="outerwear", name="Quilted Shell Jacket")
    r = canonicalize_fields(
        CanonFields(name="the zzz garment", category=None),
        {}, provider=fake, run_llm=True,
    )
    assert r.category == "outerwear"
    assert r.attributes["category"]["provenance"] == "inferred"
    assert r.used_llm
    assert fake.calls == 1


def test_user_explicit_other_is_respected():
    r = canonicalize_fields(CanonFields(name="Weird Thing", category="other"), {},
                            provider=_ExplodingProvider(), source_provenance="user_edited")
    assert r.category == "other"
    assert r.attributes["category"]["provenance"] == "user_edited"


# ---------------------------------------------------------------------------
# SIZE — default from onboarding by category (incl. footwear->shoe)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("category,expected", [
    ("top", "M"),
    ("outerwear", "L"),
    ("dress", "8"),
    ("footwear", "US 10"),
    ("bottom", "32x30"),
])
def test_size_defaults_by_category(category, expected):
    r = canonicalize_fields(
        CanonFields(name="x", category=category), _FACTS,
        provider=_ExplodingProvider(),
    )
    assert r.size == expected
    assert r.attributes["size"]["provenance"] == "default"


def test_footwear_uses_shoe_key_not_footwear_key():
    # The profile key is "shoe"; a "footwear" category must read it (regression guard).
    r = canonicalize_fields(CanonFields(name="Boots", category="footwear"),
                            {"sizes": {"shoe": "EU 44"}}, provider=_ExplodingProvider())
    assert r.size == "EU 44"


def test_unmapped_category_gets_no_default_size():
    r = canonicalize_fields(CanonFields(name="Leather Belt", category="accessory"),
                            _FACTS, provider=_ExplodingProvider())
    assert r.size is None
    assert "size" not in r.attributes


def test_provided_size_never_overwritten():
    r = canonicalize_fields(
        CanonFields(name="Tee", category="top", size="XL"), _FACTS,
        provider=_ExplodingProvider(), source_provenance="extracted",
    )
    assert r.size == "XL"                       # profile default "M" did NOT win
    assert r.attributes["size"]["provenance"] == "extracted"


def test_default_size_for_category_helper():
    sizes = {"top": "M", "shoe": {"system": "US", "value": "9"}, "dress": "6"}
    assert default_size_for_category(sizes, "top") == "M"
    assert default_size_for_category(sizes, "footwear") == "US 9"   # category->shoe key
    assert default_size_for_category(sizes, "shoes") == "US 9"      # legacy alias too
    assert default_size_for_category(sizes, "dress") == "6"
    assert default_size_for_category(sizes, "bag") is None          # unmapped
    assert default_size_for_category(None, "top") is None
    assert default_size_for_category({"top": {"system": "letter", "value": "S"}}, "top") == "S"


# ---------------------------------------------------------------------------
# NAME — never blank, never a bare category
# ---------------------------------------------------------------------------
def test_name_kept_when_descriptive():
    r = canonicalize_fields(CanonFields(name="Navy Wool Overcoat", category="outerwear"),
                            {}, provider=_ExplodingProvider(), source_provenance="extracted")
    assert r.name == "Navy Wool Overcoat"
    assert r.attributes["name"]["provenance"] == "extracted"


def test_bare_category_name_composed_from_attributes_no_llm():
    r = canonicalize_fields(
        CanonFields(name="top", category=None, brand="Nike"), {},
        run_llm=False, provider=_ExplodingProvider(),
    )
    assert r.name and r.name.strip()
    assert r.name.lower() != "top"              # not a bare category
    assert "nike" in r.name.lower()


def test_blank_name_no_signal_still_non_blank():
    r = canonicalize_fields(CanonFields(name="", category=None), {}, run_llm=False)
    assert r.name and r.name.strip()            # never blank
    assert r.name.lower() not in {"top", "bottom", "other", "dress"}


def test_name_never_blank_property():
    for nm in (None, "", "   ", "item", "clothing", "shirt"):
        r = canonicalize_fields(CanonFields(name=nm, category="top", brand="Zara"),
                                {}, run_llm=False)
        assert isinstance(r.name, str) and r.name.strip()


# ---------------------------------------------------------------------------
# COST — no LLM in the common case
# ---------------------------------------------------------------------------
def test_common_case_makes_no_llm_call():
    # Descriptive name + resolvable category + provided size -> pure rules, no LLM.
    r = canonicalize_fields(
        CanonFields(name="Blue Oxford Shirt", category="top", color="blue",
                    brand="Uniqlo", size="M"),
        _FACTS, provider=_ExplodingProvider(), run_llm=True,
    )
    assert not r.used_llm
    assert r.category == "top" and r.size == "M"


# ---------------------------------------------------------------------------
# PROVENANCE + idempotency
# ---------------------------------------------------------------------------
def test_source_provenance_manual_is_user_edited():
    r = canonicalize_fields(
        CanonFields(name="My Red Scarf", category="accessories", color="red"),
        {}, provider=_ExplodingProvider(), source_provenance="user_edited",
    )
    assert r.attributes["category"]["provenance"] == "user_edited"
    assert r.attributes["color_primary"]["provenance"] == "user_edited"
    assert r.attributes["name"]["provenance"] == "user_edited"


def test_idempotent_recanonicalize():
    f = CanonFields(name="tee", category=None, brand="Nike", size=None)
    r1 = canonicalize_fields(f, _FACTS, run_llm=False, provider=_ExplodingProvider())
    r2 = canonicalize_fields(
        CanonFields(name=r1.name, category=r1.category, brand=r1.brand,
                    color=r1.color, size=r1.size),
        _FACTS, run_llm=False, provider=_ExplodingProvider(),
    )
    assert (r1.name, r1.category, r1.size) == (r2.name, r2.category, r2.size)
    assert r2.attributes["category"]["provenance"] in ("inferred", "extracted")


# ---------------------------------------------------------------------------
# DB-backed: the manual writer routes through the chokepoint
# ---------------------------------------------------------------------------
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
    u = User(email=f"canon-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


def test_manual_create_defaults_category_and_size_from_profile(db, user1):
    db.add(StyleProfile(user_id=user1.id, facts={"sizes": {"bottom": "M", "top": "S"}}))
    db.commit()

    # Category omitted, size never provided (create_closet_item has no size param).
    item = create_closet_item(db=db, user_id=user1.id, name="Slim Fit Jeans")

    assert item.category == "bottom"                # inferred from the name, never null
    assert item.size == "M"                          # defaulted from facts.sizes[bottom]
    assert item.attributes_json["category"]["provenance"] == "inferred"
    assert item.attributes_json["size"]["provenance"] == "default"
    assert item.attributes_json["name"]["provenance"] == "user_edited"


def test_manual_create_never_null_category_without_profile(db, user1):
    item = create_closet_item(db=db, user_id=user1.id, name="mystery zzz thing")
    assert item.category == "other"                  # true last resort, still non-null
    assert item.size is None                          # no profile -> honest empty
