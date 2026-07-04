"""Wave S3 outfit collage: grid geometry, graceful degradation, item-set
caching, and the compose_outfit attach point (sufficient-only, incognito-off).
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
    _BG,
    _CELL,
    _PAD,
    compose_collage,
    get_or_create_outfit_collage,
    outfit_collage_key,
)
from app.services.stylist.profile import ProfileBlock
from app.services.stylist.tools import ToolContext, dispatch_tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _img(color, size=(400, 500)):
    return Image.new("RGB", size, color)


def _img_bytes(color, size=(400, 500)):
    out = io.BytesIO()
    _img(color, size).save(out, format="PNG")
    return out.getvalue()


def _fake_item(url="http://cdn.example/item.jpg"):
    return SimpleNamespace(id=uuid.uuid4(), image_url=url)


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    """Isolate the module-level LRU per test."""
    monkeypatch.setattr(collage, "_cache", OrderedDict())


# ---------------------------------------------------------------------------
# compose_collage: the pure PIL tiler
# ---------------------------------------------------------------------------
def _canvas_size(cols, rows):
    return (cols * _CELL + (cols + 1) * _PAD, rows * _CELL + (rows + 1) * _PAD)


@pytest.mark.parametrize(
    "n,cols,rows",
    [(2, 2, 1), (3, 2, 2), (4, 2, 2), (5, 3, 2)],
)
def test_grid_geometry(n, cols, rows):
    data = compose_collage([_img((200, 30, 30)) for _ in range(n)])
    out = Image.open(io.BytesIO(data))
    assert out.format == "JPEG"
    assert out.size == _canvas_size(cols, rows)


def _close(pixel, target, tol=14):
    return all(abs(a - b) <= tol for a, b in zip(pixel, target))


def test_background_is_neutral():
    data = compose_collage([_img((200, 30, 30)), _img((30, 30, 200))])
    out = Image.open(io.BytesIO(data)).convert("RGB")
    assert _close(out.getpixel((4, 4)), _BG)  # outer margin
    # gutter between the two cells
    assert _close(out.getpixel((_PAD + _CELL + _PAD // 2, out.height // 2)), _BG)


def test_short_last_row_is_centered():
    # 3 images -> 2x2 grid, single tile in row 2, shifted to the horizontal middle.
    data = compose_collage(
        [_img((200, 30, 30)), _img((30, 30, 200)), _img((30, 160, 60))]
    )
    out = Image.open(io.BytesIO(data)).convert("RGB")
    row2_mid_y = 2 * _PAD + _CELL + _CELL // 2
    # left edge of row 2 is background (the tile moved right)…
    assert _close(out.getpixel((_PAD + 6, row2_mid_y)), _BG)
    # …and the canvas' horizontal center hits the green tile.
    assert _close(out.getpixel((out.width // 2, row2_mid_y)), (30, 160, 60))


def test_aspect_ratio_preserved_never_upscaled():
    # A small 100x200 source must land as a 100x200 paste (thumbnail shrinks only).
    data = compose_collage([_img((200, 30, 30), (100, 200)), _img((30, 30, 200))])
    out = Image.open(io.BytesIO(data)).convert("RGB")
    cell_cx, cell_cy = _PAD + _CELL // 2, _PAD + _CELL // 2
    assert _close(out.getpixel((cell_cx, cell_cy)), (200, 30, 30))
    # 60px left of center is outside the 100px-wide tile -> background.
    assert _close(out.getpixel((cell_cx - 60, cell_cy)), _BG)


# ---------------------------------------------------------------------------
# get_or_create_outfit_collage: degradation + caching
# ---------------------------------------------------------------------------
def test_needs_two_usable_images(monkeypatch):
    calls = {"dl": 0}

    def fake_download(url):
        calls["dl"] += 1
        return (_img_bytes((10, 10, 10)), "image/png")

    monkeypatch.setattr(collage, "_download", fake_download)
    monkeypatch.setattr(collage, "_store", lambda uid, data: "http://cdn/c.jpg")

    # 0 or 1 item with an image url -> no collage, no downloads at all.
    slots = {"top": _fake_item(), "bottom": _fake_item(url=None)}
    assert get_or_create_outfit_collage(uuid.uuid4(), slots) is None
    assert calls["dl"] == 0


def test_broken_images_skipped_but_collage_survives(monkeypatch):
    def fake_download(url):
        if "dead" in url:
            return None  # unreachable photo
        if "garbage" in url:
            return (b"not an image", "image/jpeg")  # undecodable bytes
        return (_img_bytes((10, 10, 10)), "image/png")

    monkeypatch.setattr(collage, "_download", fake_download)
    monkeypatch.setattr(collage, "_store", lambda uid, data: "http://cdn/c.jpg")

    slots = {
        "top": _fake_item("http://cdn/a.jpg"),
        "bottom": _fake_item("http://cdn/dead.jpg"),
        "footwear": _fake_item("http://cdn/garbage.jpg"),
        "accessory": _fake_item("http://cdn/b.jpg"),
    }
    # 2 usable of 4 -> still a collage.
    assert get_or_create_outfit_collage(uuid.uuid4(), slots) == "http://cdn/c.jpg"

    # all dead -> None, and nothing stored.
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
        collage, "_download", lambda url: (_img_bytes((9, 9, 9)), "image/png")
    )
    monkeypatch.setattr(collage, "_store", lambda uid, data: None)
    slots = {"top": _fake_item(), "bottom": _fake_item()}
    assert get_or_create_outfit_collage(uuid.uuid4(), slots) is None
    assert len(collage._cache) == 0


def test_same_item_set_is_not_retiled(monkeypatch):
    calls = {"dl": 0, "store": 0}

    def fake_download(url):
        calls["dl"] += 1
        return (_img_bytes((10, 10, 10)), "image/png")

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

    # Same combination again — even with slots in another order: cache hit,
    # zero new downloads or uploads.
    assert (
        get_or_create_outfit_collage(user, {"bottom": bottom, "top": top})
        == "http://cdn/collage.jpg"
    )
    assert (calls["dl"], calls["store"]) == (2, 1)


def test_cache_key_semantics():
    user = uuid.uuid4()
    a, b = _fake_item("http://cdn/a.jpg"), _fake_item("http://cdn/b.jpg")
    key = outfit_collage_key(user, [a, b])
    # order-insensitive over the item SET…
    assert key == outfit_collage_key(user, [b, a])
    # …but sensitive to the user, the set, and each item's image url.
    assert key != outfit_collage_key(uuid.uuid4(), [a, b])
    assert key != outfit_collage_key(user, [a])
    changed = SimpleNamespace(id=a.id, image_url="http://cdn/a-v2.jpg")
    assert key != outfit_collage_key(user, [changed, b])


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
                     image_url="http://cdn/tee.jpg"),
        ClothingItem(user_id=user.id, name="Jeans", category="bottom",
                     image_url="http://cdn/jeans.jpg"),
    ]
    if with_footwear:
        items.append(ClothingItem(user_id=user.id, name="Sneakers", category="footwear",
                                  image_url="http://cdn/sneakers.jpg"))
    db.add_all(items); db.commit()
    return items


def _ctx(db, user, **kw):
    return ToolContext(db=db, user_id=user.id, profile=ProfileBlock(), **kw)


def test_compose_attaches_collage_url(db, user, monkeypatch):
    _closet(db, user)
    seen = {}

    def fake_collage(user_id, slots):
        seen["user_id"] = user_id
        seen["slots"] = dict(slots)
        return "http://cdn/collage.jpg"

    monkeypatch.setattr(
        "app.services.stylist.collage.get_or_create_outfit_collage", fake_collage
    )
    ctx = _ctx(db, user)
    payload = dispatch_tool(ctx, "compose_outfit", {})
    assert payload["sufficient"] is True
    assert payload["collageUrl"] == "http://cdn/collage.jpg"
    assert seen["user_id"] == user.id
    assert set(seen["slots"]) >= {"top", "bottom", "footwear"}
    # streamed + persisted payloads are the same dict -> carry the url too
    assert ctx.outfit_payloads[-1]["collageUrl"] == "http://cdn/collage.jpg"


def test_insufficient_outfit_gets_no_collage(db, user, monkeypatch):
    _closet(db, user, with_footwear=False)  # missing required slot
    monkeypatch.setattr(
        "app.services.stylist.collage.get_or_create_outfit_collage",
        lambda *a, **k: pytest.fail("collage must not run for insufficient outfits"),
    )
    payload = dispatch_tool(_ctx(db, user), "compose_outfit", {})
    assert payload["sufficient"] is False
    assert "collageUrl" not in payload


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
