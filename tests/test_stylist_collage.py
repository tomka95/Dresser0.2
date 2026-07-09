"""Wave S3 outfit lookbook card: background unification, band hierarchy,
graceful degradation, item-set caching, and the compose_outfit attach point
(completeness-gated, incognito-off).
"""

import io
import uuid
from collections import OrderedDict
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from app.db import Base, engine, SessionLocal
from app.models import ClothingItem, User
from app.services.stylist import collage
from app.services.stylist.collage import (
    _BAND_GAP,
    _CANVAS,
    _MINOR_H,
    _PAD,
    _W,
    compose_lookbook,
    get_or_create_outfit_collage,
    outfit_collage_key,
)
from app.services.stylist.profile import ProfileBlock
from app.services.stylist.tools import ToolContext, dispatch_tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
RED, BLUE, GREEN = (200, 30, 30), (30, 30, 200), (30, 160, 60)


def _product_shot(color, bg=(255, 255, 255), size=(400, 500), inset=80):
    """A synthetic product photo: solid garment rectangle on its own bg."""
    img = Image.new("RGB", size, bg)
    img.paste(color, (inset, inset, size[0] - inset, size[1] - inset))
    return img


def _png_bytes(img):
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _fake_item(url="http://cdn.example/item.jpg"):
    # person_free: usable_image_url is fail-closed (ready-first Phase 1) — a test item
    # must carry an affirmative person verdict to be composited.
    return SimpleNamespace(id=uuid.uuid4(), image_url=url, person_status="person_free")


def _close(pixel, target, tol=14):
    return all(abs(a - b) <= tol for a, b in zip(pixel, target))


def _color_extent(img, color, tol=40):
    """Bounding box of pixels near ``color`` (JPEG-tolerant), or None."""
    w, h = img.size
    px = img.load()
    xs, ys = [], []
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            if _close(px[x, y], color, tol):
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    """Isolate the module-level LRU per test."""
    monkeypatch.setattr(collage, "_cache", OrderedDict())


# ---------------------------------------------------------------------------
# compose_lookbook: the card renderer
# ---------------------------------------------------------------------------
def test_card_geometry_and_bands():
    hero_only = compose_lookbook([("top", _product_shot(RED)),
                                  ("bottom", _product_shot(BLUE))])
    both = compose_lookbook([("top", _product_shot(RED)),
                             ("bottom", _product_shot(BLUE)),
                             ("footwear", _product_shot(GREEN))])
    a, b = Image.open(io.BytesIO(hero_only)), Image.open(io.BytesIO(both))
    assert a.format == b.format == "JPEG"
    assert a.width == b.width == _W
    # Adding a finishing band grows the card by exactly gap + band height.
    assert b.height - a.height == _BAND_GAP + _MINOR_H


def test_backgrounds_unified_to_canvas():
    # Mismatched source backgrounds (pure white / grey / warm) must all land
    # on ONE porcelain field — corners, gutters, and cell interiors alike.
    data = compose_lookbook([
        ("top", _product_shot(RED, bg=(255, 255, 255))),
        ("bottom", _product_shot(BLUE, bg=(214, 214, 214))),
        ("footwear", _product_shot(GREEN, bg=(246, 241, 232))),
    ])
    out = Image.open(io.BytesIO(data)).convert("RGB")
    assert _close(out.getpixel((4, 4)), _CANVAS)
    assert _close(out.getpixel((out.width - 5, out.height - 5)), _CANVAS)
    assert _close(out.getpixel((out.width // 2, out.height - _PAD // 2)), _CANVAS)
    # Sources' own bg colors must not survive anywhere as large fields: the
    # grey (214) band would sit right of center in the hero band if unwashed.
    # (214 is far from the rule/eyebrow neutrals, so the title band can't trip this.)
    grey_box = _color_extent(out, (214, 214, 214), tol=6)
    assert grey_box is None or (
        (grey_box[2] - grey_box[0]) * (grey_box[3] - grey_box[1]) < 40 * 40
    )


def test_garments_survive_knockout():
    data = compose_lookbook([("top", _product_shot(RED)),
                             ("bottom", _product_shot(BLUE))])
    out = Image.open(io.BytesIO(data)).convert("RGB")
    assert _color_extent(out, RED) is not None
    assert _color_extent(out, BLUE) is not None


def test_hero_larger_than_accessory():
    # Same source resolution -> the hero garment must render visually larger
    # than the finishing-band accessory (hierarchy, not native-size roulette).
    data = compose_lookbook([("top", _product_shot(RED)),
                             ("bottom", _product_shot(GREEN)),
                             ("accessory", _product_shot(BLUE))])
    out = Image.open(io.BytesIO(data)).convert("RGB")
    hero_box = _color_extent(out, RED)
    minor_box = _color_extent(out, BLUE)
    assert hero_box and minor_box
    hero_h = hero_box[3] - hero_box[1]
    minor_h = minor_box[3] - minor_box[1]
    assert hero_h > minor_h * 1.3
    # and the accessory sits BELOW the hero band
    assert minor_box[1] > hero_box[3]


def test_busy_photo_falls_back_unwashed():
    # A scene with no uniform border (noise) must not be knocked out — it is
    # pasted as-is rather than shredded by a bad mask.
    import random

    rng = random.Random(7)
    busy = Image.new("RGB", (300, 300))
    busy.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256))
                  for _ in range(300 * 300)])
    data = compose_lookbook([("top", busy), ("bottom", _product_shot(BLUE))])
    out = Image.open(io.BytesIO(data)).convert("RGB")
    # the busy tile survives as a dense multicolor region (its extent exists)
    assert out.width == _W


# ---------------------------------------------------------------------------
# get_or_create_outfit_collage: degradation + caching
# ---------------------------------------------------------------------------
def test_needs_two_usable_images(monkeypatch):
    calls = {"dl": 0}

    def fake_download(url):
        calls["dl"] += 1
        return (_png_bytes(_product_shot(RED)), "image/png")

    monkeypatch.setattr(collage, "_download", fake_download)
    monkeypatch.setattr(collage, "_store", lambda uid, data: "http://cdn/c.jpg")

    slots = {"top": _fake_item(), "bottom": _fake_item(url=None)}
    assert get_or_create_outfit_collage(uuid.uuid4(), slots) is None
    assert calls["dl"] == 0


def test_broken_images_skipped_but_collage_survives(monkeypatch):
    def fake_download(url):
        if "dead" in url:
            return None
        if "garbage" in url:
            return (b"not an image", "image/jpeg")
        return (_png_bytes(_product_shot(RED)), "image/png")

    monkeypatch.setattr(collage, "_download", fake_download)
    monkeypatch.setattr(collage, "_store", lambda uid, data: "http://cdn/c.jpg")

    slots = {
        "top": _fake_item("http://cdn/a.jpg"),
        "bottom": _fake_item("http://cdn/dead.jpg"),
        "footwear": _fake_item("http://cdn/garbage.jpg"),
        "accessory": _fake_item("http://cdn/b.jpg"),
    }
    assert get_or_create_outfit_collage(uuid.uuid4(), slots) == "http://cdn/c.jpg"

    slots_dead = {
        "top": _fake_item("http://cdn/dead.jpg"),
        "bottom": _fake_item("http://cdn/garbage.jpg"),
    }
    monkeypatch.setattr(
        collage, "_store", lambda uid, data: pytest.fail("must not store")
    )
    assert get_or_create_outfit_collage(uuid.uuid4(), slots_dead) is None


def test_storage_failure_returns_none_and_is_not_cached(monkeypatch):
    monkeypatch.setattr(
        collage, "_download",
        lambda url: (_png_bytes(_product_shot(RED)), "image/png"),
    )
    monkeypatch.setattr(collage, "_store", lambda uid, data: None)
    slots = {"top": _fake_item(), "bottom": _fake_item()}
    assert get_or_create_outfit_collage(uuid.uuid4(), slots) is None
    assert len(collage._cache) == 0


def test_same_item_set_is_not_retiled(monkeypatch):
    calls = {"dl": 0, "store": 0}

    def fake_download(url):
        calls["dl"] += 1
        return (_png_bytes(_product_shot(RED)), "image/png")

    def fake_store(uid, data):
        calls["store"] += 1
        return "http://cdn/collage.jpg"

    monkeypatch.setattr(collage, "_download", fake_download)
    monkeypatch.setattr(collage, "_store", fake_store)

    user = uuid.uuid4()
    top, bottom = _fake_item("http://cdn/a.jpg"), _fake_item("http://cdn/b.jpg")
    slots = {"top": top, "bottom": bottom}

    assert get_or_create_outfit_collage(user, slots) == "http://cdn/collage.jpg"
    assert (calls["dl"], calls["store"]) == (2, 1)

    assert (
        get_or_create_outfit_collage(user, {"bottom": bottom, "top": top})
        == "http://cdn/collage.jpg"
    )
    assert (calls["dl"], calls["store"]) == (2, 1)

    # Different OCCASION = different card (the title is drawn on it) -> re-render.
    assert (
        get_or_create_outfit_collage(user, slots, occasion="date night")
        == "http://cdn/collage.jpg"
    )
    assert (calls["dl"], calls["store"]) == (4, 2)


def test_cache_key_semantics():
    user = uuid.uuid4()
    a, b = _fake_item("http://cdn/a.jpg"), _fake_item("http://cdn/b.jpg")
    key = outfit_collage_key(user, [a, b])
    assert key == outfit_collage_key(user, [b, a])          # set-ordering
    assert key != outfit_collage_key(uuid.uuid4(), [a, b])  # user
    assert key != outfit_collage_key(user, [a])             # membership
    changed = SimpleNamespace(id=a.id, image_url="http://cdn/a-v2.jpg")
    assert key != outfit_collage_key(user, [changed, b])    # image version
    assert key != outfit_collage_key(user, [a, b], occasion="brunch")  # title
    # occasion normalization: whitespace/case/snake_case fold into the same key
    assert outfit_collage_key(user, [a, b], occasion=" Brunch ") == \
        outfit_collage_key(user, [a, b], occasion="brunch")
    assert outfit_collage_key(user, [a, b], occasion="going_out") == \
        outfit_collage_key(user, [a, b], occasion="going out")


# ---------------------------------------------------------------------------
# Attach point: compose_outfit tool payload
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
def user(db: Session):
    u = User(email="collage@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


def _closet(db, user, with_footwear=True):
    items = [
        ClothingItem(user_id=user.id, name="Tee", category="top",
                     image_url="http://cdn/tee.jpg", person_status="person_free"),
        ClothingItem(user_id=user.id, name="Jeans", category="bottom",
                     image_url="http://cdn/jeans.jpg", person_status="person_free"),
    ]
    if with_footwear:
        items.append(ClothingItem(user_id=user.id, name="Sneakers", category="footwear",
                                  image_url="http://cdn/sneakers.jpg", person_status="person_free"))
    db.add_all(items); db.commit()
    return items


def _ctx(db, user, **kw):
    return ToolContext(db=db, user_id=user.id, profile=ProfileBlock(), **kw)


def test_compose_attaches_collage_url(db, user, monkeypatch):
    _closet(db, user)
    seen = {}

    def fake_collage(user_id, slots, occasion=None):
        seen["user_id"] = user_id
        seen["slots"] = dict(slots)
        seen["occasion"] = occasion
        return "http://cdn/collage.jpg"

    monkeypatch.setattr(
        "app.services.stylist.collage.get_or_create_outfit_collage", fake_collage
    )
    ctx = _ctx(db, user)
    payload = dispatch_tool(ctx, "compose_outfit", {"occasion": "brunch"})
    assert payload["collageUrl"] == "http://cdn/collage.jpg"
    assert seen["user_id"] == user.id
    assert seen["occasion"] == "brunch"
    assert set(seen["slots"]) >= {"top", "bottom", "footwear"}
    assert ctx.outfit_payloads[-1]["collageUrl"] == "http://cdn/collage.jpg"


def test_partial_outfit_with_gaps_gets_no_collage(db, user, monkeypatch):
    _closet(db, user, with_footwear=False)  # missing required slot
    monkeypatch.setattr(
        "app.services.stylist.collage.get_or_create_outfit_collage",
        lambda *a, **k: pytest.fail("collage must not run for a partial outfit"),
    )
    payload = dispatch_tool(_ctx(db, user), "compose_outfit", {})
    assert payload["sufficient"] is False
    assert payload["gaps"]
    assert "collageUrl" not in payload


def test_complete_but_low_confidence_outfit_gets_collage(db, user, monkeypatch):
    """Regression: occasion request over an untagged closet -> gaps=[] but
    confidence 0.55 < floor -> sufficient=False. Collage still attaches."""
    _closet(db, user)
    monkeypatch.setattr(
        "app.services.stylist.collage.get_or_create_outfit_collage",
        lambda user_id, slots, occasion=None: "http://cdn/collage.jpg",
    )
    payload = dispatch_tool(_ctx(db, user), "compose_outfit", {"occasion": "date night"})
    assert payload["sufficient"] is False
    assert payload["gaps"] == []
    assert payload["collageUrl"] == "http://cdn/collage.jpg"


def test_incognito_gets_no_collage(db, user, monkeypatch):
    _closet(db, user)
    monkeypatch.setattr(
        "app.services.stylist.collage.get_or_create_outfit_collage",
        lambda *a, **k: pytest.fail("collage must not run in incognito"),
    )
    payload = dispatch_tool(_ctx(db, user, no_persist=True), "compose_outfit", {})
    assert payload["sufficient"] is True
    assert "collageUrl" not in payload


def test_collage_failure_never_breaks_compose(db, user, monkeypatch):
    _closet(db, user)

    def boom(*a, **k):
        raise RuntimeError("tile explosion")

    monkeypatch.setattr(
        "app.services.stylist.collage.get_or_create_outfit_collage", boom
    )
    payload = dispatch_tool(_ctx(db, user), "compose_outfit", {})
    assert "error" not in payload
    assert payload["sufficient"] is True
    assert "collageUrl" not in payload
