"""Today's Look — GET / remix / wear + formality step-down + half-daily cache.

Runs on the real SQLite substrate (no live LLM, no network anywhere):
  * weather is inert (no saved location -> forecast_for_facts returns None),
  * calendar is inert (no CalendarAccount -> empty block); formality-target
    behavior is exercised by passing Factors() straight to the service,
  * the grid collage's download + store seams are monkeypatched so compose_grid
    runs for real (pure PIL) without hitting Supabase.

Covers: auth, cross-user reject, thin-closet starter fallback, deterministic
stability, missing-image placeholder, formality step-down completes a look,
owned-photo preference, undergarment/bag exclusion, remix variety + rate limit,
wear persistence + idempotency + learning, half-daily cache hit / signature
invalidation / remix overwrite.
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, engine
from app.models import (
    ClothingItem,
    PreferenceSignal,
    SavedOutfit,
    StyleEvent,
    TodaysLookCache,
    User,
)
from app.services.stylist import collage as collage_mod
from app.services.stylist.todays_look import Factors, compose_todays_look
from main import app
from tests._authutil import mint_supabase_token


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
def client():
    return TestClient(app)


def _tiny_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (24, 24), (120, 120, 120)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _stub_collage_io(monkeypatch):
    """Deterministic + offline collage: a tiny real PNG for every download, a
    fixed URL for every store. compose_grid still runs for real."""
    png = _tiny_png()
    monkeypatch.setattr(collage_mod, "_download", lambda url: (png, "image/png"))
    monkeypatch.setattr(
        collage_mod, "_store", lambda user_id, data: "https://cdn.test/grid.jpg"
    )
    collage_mod._cache.clear()


@pytest.fixture
def user1(db: Session):
    u = User(email="tl1@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture
def user2(db: Session):
    u = User(email="tl2@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture
def tok1(user1):
    return mint_supabase_token(sub=str(user1.id))


@pytest.fixture
def tok2(user2):
    return mint_supabase_token(sub=str(user2.id))


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def _item(db, user, name, category, **attrs):
    attrs.setdefault("image_url", f"https://cdn.test/{name}.jpg")
    attrs.setdefault("image_status", "resolved")
    it = ClothingItem(user_id=user.id, name=name, category=category, **attrs)
    db.add(it); db.commit(); db.refresh(it)
    return it


def _full_closet(db, user):
    """A top + bottom + footwear -> a sufficient (complete) outfit at any formality."""
    top = _item(db, user, "Linen shirt", "top", formality=3, warmth=2)
    bottom = _item(db, user, "Black jeans", "bottom", formality=3, warmth=2)
    shoes = _item(db, user, "Chelsea boots", "footwear", formality=3, warmth=2)
    return top, bottom, shoes


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def test_get_requires_auth(client):
    assert client.get("/todays-look").status_code in (401, 403)


def test_wear_requires_auth(client):
    assert client.post("/todays-look/wear", json={"itemIds": []}).status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET — happy path + determinism + collage
# ---------------------------------------------------------------------------
def test_get_composes_a_look(client, db, user1, tok1):
    top, bottom, shoes = _full_closet(db, user1)
    r = client.get("/todays-look", headers=_auth(tok1))
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "normal"
    assert set(body["itemIds"]) == {str(top.id), str(bottom.id), str(shoes.id)}
    assert "Linen shirt" in body["title"]
    assert body["collageUrl"] == "https://cdn.test/grid.jpg"
    assert body["caption"]
    ev = db.query(StyleEvent).filter_by(
        user_id=user1.id, event_type="outfit_shown").one()
    assert ev.properties.get("item_count") == 3
    assert "summary" not in ev.properties  # no event titles anywhere


def test_get_is_deterministic(client, db, user1, tok1):
    _full_closet(db, user1)
    a = client.get("/todays-look", headers=_auth(tok1)).json()
    b = client.get("/todays-look", headers=_auth(tok1)).json()
    assert a["itemIds"] == b["itemIds"]
    assert a["title"] == b["title"] and a["caption"] == b["caption"]


# ---------------------------------------------------------------------------
# Formality step-down (service-level; deterministic w/o a live calendar)
# ---------------------------------------------------------------------------
def test_formality_stepdown_completes_a_casual_look(db, user1):
    # A casual closet (tops out at formality 2) vs a formality-4 "work" target.
    tee = _item(db, user1, "Nike tee", "top", formality=1,
                image_status="user_uploaded", generation_status="ready")
    jeans = _item(db, user1, "Light wash jeans", "bottom", formality=2,
                  image_status="user_uploaded", generation_status="ready")
    af1 = _item(db, user1, "Air Force 1", "footwear", formality=1,
                image_status="user_uploaded", generation_status="ready")

    look = compose_todays_look(
        db, user1.id,
        factors=Factors(warmth=2, occasion="work", formality_target=4),
    )
    # A COMPLETE look, not a starter, even below the ideal formality.
    assert look.kind == "normal"
    assert set(look.item_ids) == {str(tee.id), str(jeans.id), str(af1.id)}
    assert look.formality is not None and look.formality < 4  # stepped down
    assert "sharper" in look.caption.lower()  # gentle below-ideal note


def test_real_closet_shape_yields_wearable_look(db, user1):
    """Reproduces the CONFIRMED-LIVE closet (16 items) that previously returned an
    empty 'starter' with junk. The formality-4 'work' target must now step down to
    a COMPLETE look built from the real user photos — not the image-less SHEIN
    halter or a sports bra."""
    up = dict(image_status="user_uploaded", generation_status="ready")
    ph = dict(image_url=None, image_status="placeholder")
    # Real owned photos (the wearable casual set)
    _item(db, user1, "Nike T-shirt", "top", formality=1, **up)
    _item(db, user1, "Plaid short-sleeve shirt", "top", formality=2, **up)
    _item(db, user1, "Light wash jeans", "bottom", formality=2, **up)
    _item(db, user1, "White-Red Nike Air Force 1", "footwear", formality=1, **up)
    # Resolved product images that are NOT valid primaries (undergarments)
    _item(db, user1, "Wunder Train Strappy Racer Bra Light Support", "top")
    _item(db, user1, "Flow Y Bra Nulu Light Support", "top",
          sub_category="sports_bra", formality=1)
    # Resolved athletic bottoms (real images, formality 1)
    _item(db, user1, "lululemon Align High-Rise Short", "bottom", formality=1)
    _item(db, user1, "Wunder Train High-Rise Tight", "bottom", formality=1)
    # Image-less receipt junk (placeholders)
    _item(db, user1, "SHEIN ICON Going Out Backless Halter Top", "top",
          formality=3, **ph)
    _item(db, user1, "Metal Clip Hair Accessory Barrette Claw Clips", "accessory", **ph)
    _item(db, user1, "Leopard Print Handbag Lunch Bag", "accessory",
          sub_category="tote_bag", formality=1, **ph)
    _item(db, user1, "MUSERA Boxy Denim Jacket", "outerwear", formality=2, **ph)

    look = compose_todays_look(
        db, user1.id,
        factors=Factors(warmth=2, occasion="work", formality_target=4),
    )
    assert look.kind == "normal"
    assert look.formality == 2  # stepped 4 -> 2 to reach the casual set
    by_slot = {it["category"]: it for it in look.items}
    # Top is a real garment photo, never the image-less halter or a bra.
    assert by_slot["top"]["name"] in {"Nike T-shirt", "Plaid short-sleeve shirt"}
    assert by_slot["top"]["hasImage"] is True
    assert by_slot["footwear"]["name"] == "White-Red Nike Air Force 1"
    assert by_slot["bottom"]["hasImage"] is True
    # No bra / halter / bag anywhere in the look.
    names = " ".join(it["name"].lower() for it in look.items)
    assert "bra" not in names and "halter" not in names and "handbag" not in names
    assert look.collage_url == "https://cdn.test/grid.jpg"


def test_no_complete_look_at_any_formality_is_starter(db, user1):
    _item(db, user1, "Lonely tee", "top", formality=2)  # no bottom/footwear
    look = compose_todays_look(
        db, user1.id, factors=Factors(occasion="work", formality_target=4))
    assert look.kind == "starter"
    assert look.note


# ---------------------------------------------------------------------------
# Prefer owned real photos; exclude undergarments / bags / hair accessories
# ---------------------------------------------------------------------------
def test_prefers_owned_real_photo_over_imageless(db, user1):
    real = _item(db, user1, "Real tee", "top", formality=2,
                 image_status="user_uploaded", generation_status="ready")
    _item(db, user1, "Receipt tee", "top", formality=2,
          image_url=None, image_status="placeholder")
    _item(db, user1, "Jeans", "bottom", formality=2,
          image_status="user_uploaded", generation_status="ready")
    _item(db, user1, "Sneakers", "footwear", formality=2,
          image_status="user_uploaded", generation_status="ready")

    look = compose_todays_look(db, user1.id, factors=Factors(formality_target=2))
    ids = set(look.item_ids)
    assert str(real.id) in ids
    top_names = [it["name"] for it in look.items if it["category"] == "top"]
    assert top_names == ["Real tee"]  # the image-less receipt top never wins


def test_excludes_undergarments_and_bags(db, user1):
    bra = _item(db, user1, "Strappy Racer Bra Light Support", "top", formality=1)
    bag = _item(db, user1, "Leopard Handbag Lunch Bag", "accessory",
                sub_category="tote_bag", formality=1)
    tee = _item(db, user1, "Cotton tee", "top", formality=2,
                image_status="user_uploaded", generation_status="ready")
    _item(db, user1, "Jeans", "bottom", formality=2)
    _item(db, user1, "Sneakers", "footwear", formality=2)

    look = compose_todays_look(db, user1.id, factors=Factors(formality_target=2))
    ids = set(look.item_ids)
    assert str(bra.id) not in ids   # undergarment never a primary
    assert str(bag.id) not in ids   # bag never a primary
    assert str(tee.id) in ids       # the real garment is chosen instead


# ---------------------------------------------------------------------------
# Thin / empty closet -> starter (never 500)
# ---------------------------------------------------------------------------
def test_thin_closet_returns_starter(client, db, user1, tok1):
    _item(db, user1, "Lonely tee", "top")
    body = client.get("/todays-look", headers=_auth(tok1)).json()
    assert body["kind"] == "starter" and body["note"]


def test_empty_closet_returns_starter(client, db, user1, tok1):
    assert client.get("/todays-look", headers=_auth(tok1)).json()["kind"] == "starter"


# ---------------------------------------------------------------------------
# Missing image -> placeholder tile, never skipped, never breaks
# ---------------------------------------------------------------------------
def test_missing_image_still_placed(client, db, user1, tok1):
    _item(db, user1, "Linen shirt", "top",
          image_status="user_uploaded", generation_status="ready")
    _item(db, user1, "Black jeans", "bottom",
          image_status="user_uploaded", generation_status="ready")
    shoes = _item(db, user1, "Mystery shoes", "footwear",
                  image_url=None, image_status="pending")
    body = client.get("/todays-look", headers=_auth(tok1)).json()
    assert str(shoes.id) in body["itemIds"]        # not skipped
    by_id = {it["id"]: it for it in body["items"]}
    assert by_id[str(shoes.id)]["hasImage"] is False
    assert body["collageUrl"] == "https://cdn.test/grid.jpg"  # still renders


# ---------------------------------------------------------------------------
# Half-daily cache
# ---------------------------------------------------------------------------
def test_cache_hit_returns_identical_without_recompute(client, db, user1, tok1):
    _full_closet(db, user1)
    first = client.get("/todays-look", headers=_auth(tok1)).json()
    second = client.get("/todays-look", headers=_auth(tok1)).json()
    assert first == second
    # Composed once => exactly one outfit_shown and one cache row.
    assert db.query(StyleEvent).filter_by(
        user_id=user1.id, event_type="outfit_shown").count() == 1
    assert db.query(TodaysLookCache).filter_by(user_id=user1.id).count() == 1


def test_grid_collage_background_is_warm_offwhite():
    # grid-v3: a CLEARLY warm off-white (#F3EEE6) that visibly differs from white
    # and from the near-white porcelain.
    assert collage_mod._GRID_BG == (243, 238, 230)
    assert collage_mod._GRID_BG != (255, 255, 255)
    assert collage_mod._GRID_BG != collage_mod._CANVAS
    assert collage_mod._GRID_LAYOUT_VERSION == "grid-v3"
    assert collage_mod._GRID_FILL >= 0.85  # items fill their cell


def test_grid_collage_dimensions_are_landscape_strip():
    # 3 items -> 1080 x 478 landscape strip (matches the card container ratio).
    from PIL import Image

    png = _tiny_png()
    data = collage_mod.compose_grid([
        Image.open(io.BytesIO(png)).convert("RGB") for _ in range(3)
    ])
    w, h = Image.open(io.BytesIO(data)).size
    assert (w, h) == (1080, 478)


def test_collage_version_bump_invalidates_cache(client, db, user1, tok1, monkeypatch):
    # The collage layout version is folded into factor_signature, so a bg/layout
    # bump forces a one-time recompute even when weather/occasion/closet are
    # unchanged — a stale collage URL can never persist.
    import app.api.routes.todays_look as route

    _full_closet(db, user1)
    client.get("/todays-look", headers=_auth(tok1))  # miss -> compose + cache
    assert db.query(StyleEvent).filter_by(
        user_id=user1.id, event_type="outfit_shown").count() == 1

    # Simulate the cached row having been rendered under a DIFFERENT grid version.
    monkeypatch.setattr(route, "_GRID_LAYOUT_VERSION", "grid-vOLD")
    client.get("/todays-look", headers=_auth(tok1))  # signature differs -> recompute
    assert db.query(StyleEvent).filter_by(
        user_id=user1.id, event_type="outfit_shown").count() == 2


def test_cache_invalidates_on_closet_change(client, db, user1, tok1):
    _full_closet(db, user1)
    client.get("/todays-look", headers=_auth(tok1))
    # Add a garment -> closet signature changes -> next GET recomposes.
    _item(db, user1, "Extra jacket", "outerwear", formality=3, warmth=3)
    client.get("/todays-look", headers=_auth(tok1))
    assert db.query(StyleEvent).filter_by(
        user_id=user1.id, event_type="outfit_shown").count() == 2


def test_remix_overwrites_cache_and_get_returns_it(client, db, user1, tok1):
    # Two of each slot so remix can produce a COMPLETE different look.
    a_top = _item(db, user1, "Top A", "top", formality=2)
    a_bot = _item(db, user1, "Bottom A", "bottom", formality=2)
    a_shoe = _item(db, user1, "Shoe A", "footwear", formality=2)
    _item(db, user1, "Top B", "top", formality=2)
    _item(db, user1, "Bottom B", "bottom", formality=2)
    _item(db, user1, "Shoe B", "footwear", formality=2)

    remix = client.post(
        "/todays-look/remix", headers=_auth(tok1),
        json={"itemIds": [str(a_top.id), str(a_bot.id), str(a_shoe.id)]},
    ).json()
    # A DIFFERENT complete look (minimal swap), not a starter.
    assert remix["kind"] == "normal"
    assert set(remix["itemIds"]) != {str(a_top.id), str(a_bot.id), str(a_shoe.id)}
    # A follow-up GET returns the remixed look verbatim (cache overwritten),
    # without composing again (no extra outfit_shown from the GET hit).
    got = client.get("/todays-look", headers=_auth(tok1)).json()
    assert got["itemIds"] == remix["itemIds"]
    assert db.query(StyleEvent).filter_by(
        user_id=user1.id, event_type="outfit_shown").count() == 1  # remix only


# ---------------------------------------------------------------------------
# Remix — completeness-preserving minimal swap (never a worse starter)
# ---------------------------------------------------------------------------
def _casual_swappable(db, user):
    """Two tops, one sole bottom, one sole footwear — remix must swap the top and
    KEEP the sole bottom + footwear (the live-confirmed failure shape)."""
    up = dict(image_status="user_uploaded", generation_status="ready")
    plaid = _item(db, user, "Plaid shirt", "top", formality=2, **up)
    tee = _item(db, user, "Nike tee", "top", formality=1, **up)
    jeans = _item(db, user, "Light wash jeans", "bottom", formality=2, **up)
    af1 = _item(db, user, "Air Force 1", "footwear", formality=1, **up)
    return plaid, tee, jeans, af1


def test_remix_swaps_top_keeps_sole_footwear_and_bottom(client, db, user1, tok1):
    plaid, tee, jeans, af1 = _casual_swappable(db, user1)
    r = client.post(
        "/todays-look/remix", headers=_auth(tok1),
        json={"itemIds": [str(plaid.id), str(jeans.id), str(af1.id)]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "normal"                    # NEVER starter
    assert str(af1.id) in body["itemIds"]              # sole footwear kept
    assert str(jeans.id) in body["itemIds"]            # sole bottom kept
    assert str(plaid.id) not in body["itemIds"]        # the swappable slot changed
    tops = [it for it in body["items"] if it["category"] == "top"]
    assert [t["name"] for t in tops] == ["Nike tee"]   # swapped to the alt top
    assert body["collageUrl"] == "https://cdn.test/grid.jpg"


def test_remix_never_starter_when_get_is_normal(client, db, user1, tok1):
    plaid, _tee, jeans, af1 = _casual_swappable(db, user1)
    got = client.get("/todays-look", headers=_auth(tok1)).json()
    assert got["kind"] == "normal"
    remix = client.post(
        "/todays-look/remix", headers=_auth(tok1),
        json={"itemIds": got["itemIds"]},
    ).json()
    assert remix["kind"] == "normal"


def test_remix_degrades_to_current_when_no_variety(client, db, user1, tok1):
    # Exactly one item per slot -> no alternative -> keep the current complete look.
    up = dict(image_status="user_uploaded", generation_status="ready")
    plaid = _item(db, user1, "Plaid shirt", "top", formality=2, **up)
    jeans = _item(db, user1, "Jeans", "bottom", formality=2, **up)
    af1 = _item(db, user1, "Air Force 1", "footwear", formality=1, **up)
    current = [str(plaid.id), str(jeans.id), str(af1.id)]
    body = client.post(
        "/todays-look/remix", headers=_auth(tok1), json={"itemIds": current},
    ).json()
    assert body["kind"] == "normal"                     # not a starter
    assert set(body["itemIds"]) == set(current)         # unchanged complete look
    assert "best full look" in body["caption"].lower()  # gentle note


def test_remix_prefers_real_photo_on_swap(client, db, user1, tok1):
    up = dict(image_status="user_uploaded", generation_status="ready")
    plaid = _item(db, user1, "Plaid shirt", "top", formality=2, **up)
    real_tee = _item(db, user1, "Real tee", "top", formality=1, **up)
    _item(db, user1, "Receipt tee", "top", formality=1,
          image_url=None, image_status="placeholder")
    jeans = _item(db, user1, "Jeans", "bottom", formality=2, **up)
    af1 = _item(db, user1, "Air Force 1", "footwear", formality=1, **up)
    body = client.post(
        "/todays-look/remix", headers=_auth(tok1),
        json={"itemIds": [str(plaid.id), str(jeans.id), str(af1.id)]},
    ).json()
    tops = [it["name"] for it in body["items"] if it["category"] == "top"]
    assert tops == ["Real tee"]  # image-less receipt top never wins the swap


def test_remix_excludes_undergarment_on_swap(client, db, user1, tok1):
    up = dict(image_status="user_uploaded", generation_status="ready")
    plaid = _item(db, user1, "Plaid shirt", "top", formality=2, **up)
    bra = _item(db, user1, "Strappy Racer Bra Light Support", "top", formality=1)
    jeans = _item(db, user1, "Jeans", "bottom", formality=2, **up)
    af1 = _item(db, user1, "Air Force 1", "footwear", formality=1, **up)
    body = client.post(
        "/todays-look/remix", headers=_auth(tok1),
        json={"itemIds": [str(plaid.id), str(jeans.id), str(af1.id)]},
    ).json()
    assert body["kind"] == "normal"
    assert str(bra.id) not in body["itemIds"]  # a bra never becomes the swap


def test_remix_excludes_current_items(client, db, user1, tok1):
    top, bottom, shoes = _full_closet(db, user1)
    alt = _item(db, user1, "White sneakers", "footwear", formality=3, warmth=2)
    r = client.post("/todays-look/remix", headers=_auth(tok1),
                    json={"itemIds": [str(top.id), str(bottom.id), str(shoes.id)]})
    assert r.status_code == 200
    body = r.json()
    assert str(shoes.id) not in body["itemIds"]
    assert str(alt.id) in body["itemIds"]
    assert db.query(StyleEvent).filter_by(
        user_id=user1.id, event_type="outfit_reject").count() == 1


def test_remix_rate_limited(client, db, user1, tok1, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "CHAT_RATE_LIMIT_PER_MINUTE", 2)
    _full_closet(db, user1)
    codes = [
        client.post("/todays-look/remix", headers=_auth(tok1),
                    json={"itemIds": []}).status_code
        for _ in range(4)
    ]
    assert 429 in codes


def test_remix_rejects_foreign_item_ids(client, db, user1, user2, tok2):
    top, _b, _s = _full_closet(db, user1)  # belong to user1
    body = client.post("/todays-look/remix", headers=_auth(tok2),
                       json={"itemIds": [str(top.id)]}).json()
    assert str(top.id) not in body["itemIds"]
    assert body["kind"] == "starter"  # user2 has an empty closet


# ---------------------------------------------------------------------------
# Wear — persistence, cross-user reject, idempotency, learning
# ---------------------------------------------------------------------------
def test_wear_persists_worn_outfit(client, db, user1, tok1):
    top, bottom, shoes = _full_closet(db, user1)
    ids = [str(top.id), str(bottom.id), str(shoes.id)]
    r = client.post("/todays-look/wear", headers=_auth(tok1), json={"itemIds": ids})
    assert r.status_code == 201
    body = r.json()
    assert body["ok"] and body["itemCount"] == 3 and body["idempotent"] is False
    saved = db.query(SavedOutfit).filter_by(user_id=user1.id).one()
    assert saved.source == "composer" and saved.status == "worn" and saved.worn_at
    types = {e.event_type for e in db.query(StyleEvent).filter_by(user_id=user1.id)}
    assert {"outfit_accept", "outfit_worn"} <= types
    assert db.query(PreferenceSignal).filter_by(
        user_id=user1.id, source="outfit_feedback").count() >= 1
    db.refresh(top)
    assert int(top.wear_count or 0) == 1


def test_wear_is_idempotent_per_day(client, db, user1, tok1):
    top, bottom, shoes = _full_closet(db, user1)
    ids = [str(top.id), str(bottom.id), str(shoes.id)]
    first = client.post("/todays-look/wear", headers=_auth(tok1),
                        json={"itemIds": ids}).json()
    second = client.post("/todays-look/wear", headers=_auth(tok1),
                         json={"itemIds": list(reversed(ids))}).json()
    assert second["idempotent"] is True
    assert second["outfitId"] == first["outfitId"]
    assert db.query(SavedOutfit).filter_by(user_id=user1.id).count() == 1


def test_wear_rejects_foreign_item_ids(client, db, user1, user2, tok2):
    top, _b, _s = _full_closet(db, user1)
    r = client.post("/todays-look/wear", headers=_auth(tok2),
                    json={"itemIds": [str(top.id)]})
    assert r.status_code == 422
    assert db.query(SavedOutfit).filter_by(user_id=user2.id).count() == 0


def test_wear_requires_item_ids(client, db, user1, tok1):
    assert client.post("/todays-look/wear", headers=_auth(tok1),
                       json={"itemIds": []}).status_code == 422
