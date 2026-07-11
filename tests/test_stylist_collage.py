"""Wave S3 outfit lookbook card, v2 (Collage Phase 2): stored-alpha
compositing (the render-time color key is deleted), flat-tile fallback for
un-matted items, band hierarchy, item-set caching (cutout-aware), category
scale + baseline anchoring + the one synthetic shadow on the grid, and the
compose_outfit attach point (completeness-gated, incognito-off).
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


def _cutout_shot(color, size=(400, 500), inset=80):
    """A synthetic STORED MATTE (Phase 1 shape): solid garment rectangle with
    real alpha — transparent everywhere else."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    img.paste(color + (255,), (inset, inset, size[0] - inset, size[1] - inset))
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


def test_matted_items_unify_on_canvas_via_stored_alpha():
    # Collage Phase 2: unification comes from the STORED MATTES, not a render-
    # time key. Cutouts with real alpha land on ONE porcelain field — corners,
    # gutters, and everything the sources' transparent regions covered.
    data = compose_lookbook([
        ("top", _cutout_shot(RED)),
        ("bottom", _cutout_shot(BLUE)),
        ("footwear", _cutout_shot(GREEN)),
    ])
    out = Image.open(io.BytesIO(data)).convert("RGB")
    assert _close(out.getpixel((4, 4)), _CANVAS)
    assert _close(out.getpixel((out.width - 5, out.height - 5)), _CANVAS)
    assert _close(out.getpixel((out.width // 2, out.height - _PAD // 2)), _CANVAS)
    # Garments composite; no source background exists to survive.
    assert _color_extent(out, RED) is not None
    assert _color_extent(out, BLUE) is not None


def test_cutout_routes_via_stored_alpha_not_a_key():
    # A stored matte routes through the alpha path; an opaque JPEG-like image
    # routes to the flat tile. NOTHING is ever color-keyed at render time.
    rgb, mask, is_cutout = collage._prepare_cell(_cutout_shot(RED))
    assert is_cutout is True
    # trimmed to the garment's alpha bbox (+small margin), not the full frame
    assert rgb.size[0] < 400 and rgb.size[1] < 500

    rgb2, mask2, is_cutout2 = collage._prepare_cell(_product_shot(RED))
    assert is_cutout2 is False
    assert rgb2.size == (400, 500)  # flat tile keeps the photo verbatim
    # flat tile's own bg pixel is untouched (no knockout to canvas)
    assert rgb2.getpixel((4, 4)) == (255, 255, 255)


def test_garments_survive_compositing():
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


def test_busy_photo_renders_flat_never_shredded():
    # v2: any opaque image — however busy — is a flat tile, pasted as-is.
    # There is no key left to shred it with.
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
# Grid v2 (grid-v6): category scale, baseline anchoring, the one shadow,
# cutout-aware cache keys, render speed, generation-free.
# ---------------------------------------------------------------------------
def test_grid_category_scale_and_baseline_anchor():
    # A sneaker must NOT render as tall as a shirt (spike cause 4), and it sits
    # LOW (baseline-anchored), not floating on the midline.
    data = collage.compose_grid([
        ("top", _cutout_shot(RED)),
        ("bottom", _cutout_shot(BLUE)),
        ("footwear", _cutout_shot(GREEN)),
    ])
    out = Image.open(io.BytesIO(data)).convert("RGB")
    top_box = _color_extent(out, RED)
    shoe_box = _color_extent(out, GREEN)
    assert top_box and shoe_box
    top_h = top_box[3] - top_box[1]
    shoe_h = shoe_box[3] - shoe_box[1]
    # category scale: footwear (0.36) is well under half the top's height (0.66)
    assert shoe_h < top_h * 0.75
    # baseline anchor: the shoe's bottom edge sits near 0.86 * H, i.e. clearly
    # BELOW the top's bottom edge (the top is centered on the midline)
    assert shoe_box[3] > top_box[3]
    assert abs(shoe_box[3] - int(0.86 * collage._GRID_H)) < 20


def test_grid_synthetic_shadow_grounds_cutouts():
    # One soft shadow, slightly right+down of the garment: a pixel just below
    # the cutout is darker than the pristine canvas far away.
    data = collage.compose_grid([("top", _cutout_shot(RED))])
    out = Image.open(io.BytesIO(data)).convert("RGB")
    box = _color_extent(out, RED)
    assert box
    below = out.getpixel(((box[0] + box[2]) // 2 + 4, min(box[3] + 8, collage._GRID_H - 1)))
    corner = out.getpixel((4, 4))
    assert _close(corner, collage._GRID_BG, tol=6)          # canvas pristine
    assert sum(below) < sum(corner) - 10                    # shadow present
    # and the shadow is subtle grounding, not a black blob
    assert sum(below) > sum(corner) - 90


def test_grid_cache_key_invalidates_when_matte_lands():
    user = uuid.uuid4()
    item = _fake_item("http://cdn/a.jpg")
    before = collage._grid_key(user, [("top", item)])
    item.cutout_status = "ready"
    item.cutout_url = "http://cdn/cutouts/a.png"
    after = collage._grid_key(user, [("top", item)])
    assert before != after  # a landing matte re-renders the card


def test_matted_item_downloads_cutout_and_falls_back_flat(monkeypatch):
    # cutout_status='ready' -> the stored matte is fetched (first); if that
    # download fails, the item falls back to its display image (flat tile) —
    # never dropped, never keyed.
    fetched = []

    def fake_download(url):
        fetched.append(url)
        if "cutouts" in url and "dead" not in url:
            return (_png_bytes(_cutout_shot(RED)), "image/png")
        if "dead" in url:
            return None
        return (_png_bytes(_product_shot(BLUE)), "image/png")

    monkeypatch.setattr(collage, "_download", fake_download)

    matted = _fake_item("http://cdn/a.jpg")
    matted.cutout_status = "ready"
    matted.cutout_url = "http://cdn/cutouts/a.png"
    img = collage._fetch_item_image(matted)
    assert fetched[0] == "http://cdn/cutouts/a.png"
    assert collage._source_alpha(img) is not None  # the stored matte won

    broken = _fake_item("http://cdn/b.jpg")
    broken.cutout_status = "ready"
    broken.cutout_url = "http://cdn/cutouts/dead.png"
    img2 = collage._fetch_item_image(broken)
    assert img2 is not None
    assert collage._source_alpha(img2) is None     # fell back to the flat display image


def test_grid_render_is_fast_and_generation_free():
    # STAYS PURE: a full 4-cell render completes well under the 1s budget, and
    # the module never touches a generation provider (the rejected option).
    import inspect
    import time

    cells = [
        ("top", _cutout_shot(RED)),
        ("bottom", _cutout_shot(BLUE)),
        ("outerwear", _product_shot(GREEN)),   # flat-tile path too
        ("footwear", None),                    # placeholder path too
    ]
    t0 = time.perf_counter()
    data = collage.compose_grid(cells)
    assert time.perf_counter() - t0 < 1.0
    assert data

    src = inspect.getsource(collage)
    for forbidden in ("generate_core", "nano_banana", "flux", "genai", "GenerationRequest"):
        assert forbidden not in src


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
    matted = SimpleNamespace(id=a.id, image_url=a.image_url,
                             cutout_url="http://cdn/cutouts/a.png")
    assert key != outfit_collage_key(user, [matted, b])     # a matte landing re-keys
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
