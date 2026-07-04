"""Outfit lookbook card (Wave S3, polished): ONE editorial flat-lay image
composed from the outfit's own item photos. Pure PIL on already-stored
cutouts — no generation API, no model, no new pixels invented.

DESIGN (why it doesn't look like a contact sheet):
  * Every item is NORMALIZED first: its product-shot background (sampled from
    the image border) is knocked out to the card's shared porcelain canvas
    with a feathered mask, then the item is trimmed to its content box — so
    grey cutout cards and warm-white shop photos land on ONE seamless field.
  * HIERARCHY, not a naive grid: garments (top/dress/bottom/outerwear) sit in
    a large hero band; footwear + accessories sit below at ~60% scale in a
    centered finishing band. Items are scaled to a fixed fill fraction of
    their cell, so no photo's native resolution dominates the composition.
  * A quiet title band — tracked-caps "YOUR LOOK · <OCCASION>" over a hairline
    rule with a small mint tick (the app's accent) — and a soft contact shadow
    under each item make it read as a designed card, not tiles.

CACHING — unchanged contract, two layers:
  * in-process LRU keyed by sha256(layout version + occasion + user + sorted
    "id:image_url" pairs); the version string invalidates every pre-polish
    cache entry, and the occasion is part of the key because it is drawn onto
    the card;
  * the upload goes through the content-addressed image_blobs dedup — the
    renderer is deterministic, so identical inputs converge to one stored
    object even across restarts.

FAILURE POSTURE — unchanged: items without an image url and images that fail
to download/decode are skipped; fewer than 2 usable images, or any storage
failure, yields None. Missing fonts (Pillow < 10.1) just drop the title band.
Nothing here may ever break compose_outfit.
"""
from __future__ import annotations

import hashlib
import io
import logging
import threading
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from PIL import Image, ImageChops, ImageFilter, ImageFont, ImageDraw

from app.models import ClothingItem

# Reused download seam (module attr so tests monkeypatch collage._download).
from app.photo_closet.generation_service import _download_bytes as _download

logger = logging.getLogger(__name__)

# --- Palette (porcelain field, editorial neutrals, one mint accent) ----------
_CANVAS = (250, 249, 247)   # porcelain: blends product-shot whites, warm not clinical
_EYEBROW = (138, 133, 124)  # taupe tracked caps
_TITLE = (42, 42, 40)       # charcoal occasion text
_RULE = (229, 226, 220)     # hairline
_MINT = (75, 226, 214)      # app accent --mint (#4be2d6)

# --- Geometry -----------------------------------------------------------------
_W = 1080                 # canvas width; height derives from the bands present
_PAD = 64                 # outer margin
_GUTTER = 48              # space between hero cells
_HERO_H = 430             # hero band cell height
_MINOR_W, _MINOR_H = 240, 260   # finishing band cell size
_MINOR_GAP = 56           # space between finishing items
_BAND_GAP = 36            # hero band -> finishing band
_FILL = 0.90              # item long-edge fill fraction of its cell
_MAX_UPSCALE = 2.2        # small cutouts may grow this far, never more (blur guard)
_JPEG_QUALITY = 92

# Background knockout: border must be near-uniform to count as a product shot.
_KNOCK_TOL = 26           # per-channel distance from sampled border color
_MIN_BG_FRACTION = 0.30   # less "background" than this = busy photo, keep as-is
_TRIM_MARGIN = 0.05       # breathing room kept around the trimmed content box

_MIN_IMAGES = 2           # a 1-tile card adds nothing over the item thumbnail

_LAYOUT_VERSION = "lookbook-v2"

# Hero band = the garments that make the silhouette; finishing band = the rest.
_HERO_SLOTS = ("top", "dress", "bottom", "outerwear")
_MINOR_SLOTS = ("footwear", "accessory")

# ---------------------------------------------------------------------------
# In-process LRU: item-set hash -> stored collage URL
# ---------------------------------------------------------------------------
_CACHE_MAX = 256
_cache: "OrderedDict[str, str]" = OrderedDict()
_cache_lock = threading.Lock()


def _cache_get(key: str) -> Optional[str]:
    with _cache_lock:
        url = _cache.get(key)
        if url is not None:
            _cache.move_to_end(key)
        return url


def _cache_put(key: str, url: str) -> None:
    with _cache_lock:
        _cache[key] = url
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)


def _norm_occasion(occasion: Optional[str]) -> str:
    """Display/key form: snake_case and hyphens fold to spaces ('going_out' ->
    'GOING OUT'), whitespace collapsed, uppercased, bounded."""
    cleaned = str(occasion or "").replace("_", " ").replace("-", " ")
    return " ".join(cleaned.split()).upper()[:28]


def outfit_collage_key(
    user_id: UUID, items: List[ClothingItem], occasion: Optional[str] = None
) -> str:
    """Item-SET hash: sorted "id:image_url" pairs + user + layout version +
    occasion (it is drawn on the card). Order-insensitive over the items."""
    pairs = sorted(f"{item.id}:{item.image_url}" for item in items)
    head = [_LAYOUT_VERSION, f"occ={_norm_occasion(occasion)}", str(user_id)]
    return hashlib.sha256("|".join(head + pairs).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Item normalization: shared background + content trim
# ---------------------------------------------------------------------------
def _border_color(rgb: Image.Image) -> Tuple[int, int, int]:
    """Median color of the image border (sampled on a 32px thumbnail)."""
    small = rgb.resize((32, 32))
    px = small.load()
    edge = [px[x, y] for x in range(32) for y in (0, 31)]
    edge += [px[x, y] for y in range(32) for x in (0, 31)]
    meds = []
    for ch in range(3):
        vals = sorted(p[ch] for p in edge)
        meds.append(vals[len(vals) // 2])
    return tuple(meds)


def _normalize_item(img: Image.Image) -> Tuple[Image.Image, Optional[Image.Image]]:
    """Knock the item's own background out to the shared canvas color and trim
    to the content box. Returns (normalized RGB, content mask or None).

    A busy photo (border not near-uniform / hardly any background) is returned
    untouched with no mask — it will sit as a plain rectangle, which is the
    honest fallback for a non-product-shot source.
    """
    rgb = img.convert("RGB")
    bg = _border_color(rgb)
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, bg))
    r, g, b = diff.split()
    dist = ImageChops.lighter(ImageChops.lighter(r, g), b)  # max channel delta
    content = dist.point(lambda v: 255 if v > _KNOCK_TOL else 0)
    # Despeckle so jpeg noise / shadows don't ruin the trim box.
    content = content.filter(ImageFilter.MedianFilter(5))

    hist = content.histogram()
    bg_fraction = hist[0] / max(1, rgb.width * rgb.height)
    if bg_fraction < _MIN_BG_FRACTION:
        return rgb, None  # busy scene: no reliable background to unify

    feather = content.filter(ImageFilter.GaussianBlur(2))
    flat = Image.new("RGB", rgb.size, _CANVAS)
    flat.paste(rgb, (0, 0), feather)

    box = content.getbbox()
    if box:
        mx = int(max(box[2] - box[0], box[3] - box[1]) * _TRIM_MARGIN)
        box = (
            max(0, box[0] - mx),
            max(0, box[1] - mx),
            min(rgb.width, box[2] + mx),
            min(rgb.height, box[3] + mx),
        )
        flat, content = flat.crop(box), content.crop(box)
    return flat, content


def _fit(size: Tuple[int, int], cell_w: int, cell_h: int) -> Tuple[int, int]:
    """Scale to fill _FILL of the cell (long-edge fit), bounded upscaling."""
    w, h = size
    scale = min(_FILL * cell_w / w, _FILL * cell_h / h, _MAX_UPSCALE)
    return max(1, int(w * scale)), max(1, int(h * scale))


def _place(
    canvas: Image.Image,
    item: Tuple[Image.Image, Optional[Image.Image]],
    cx: int, cy: int, cell_w: int, cell_h: int,
) -> None:
    """Center one normalized item in its cell with a soft contact shadow."""
    flat, mask = item
    w, h = _fit(flat.size, cell_w, cell_h)
    flat = flat.resize((w, h), Image.LANCZOS)
    x, y = cx - w // 2, cy - h // 2
    if mask is not None:
        mask = mask.resize((w, h), Image.LANCZOS)
        shadow = mask.filter(ImageFilter.GaussianBlur(12)).point(lambda v: v * 10 // 100)
        canvas.paste((203, 200, 194), (x, y + 10), shadow)  # grounded, 10% depth
        canvas.paste(flat, (x, y), mask.filter(ImageFilter.GaussianBlur(2)))
    else:
        canvas.paste(flat, (x, y))


# ---------------------------------------------------------------------------
# Title band (tracked caps; silently dropped when no scalable font exists)
# ---------------------------------------------------------------------------
def _font(size: int):
    try:
        return ImageFont.load_default(size=size)  # Pillow >= 10.1 (embedded face)
    except TypeError:
        return None


def _tracked_caps(draw: "ImageDraw.ImageDraw", xy, text, font, fill, tracking: int) -> int:
    """Draw letter-spaced caps (PIL has no tracking); returns the end x."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking
    return int(x - tracking)


def _title_band(canvas: Image.Image, occasion: Optional[str]) -> int:
    """Draw the header; returns the y where content starts."""
    font = _font(34)
    if font is None:
        return _PAD  # no scalable font on this Pillow: card just has no title
    draw = ImageDraw.Draw(canvas)
    y = _PAD
    try:
        x_end = _tracked_caps(draw, (_PAD, y), "YOUR LOOK", font, _EYEBROW, 8)
        occ = _norm_occasion(occasion)
        if occ:
            x_end = _tracked_caps(draw, (x_end + 18, y), "·", font, _EYEBROW, 8)
            _tracked_caps(draw, (x_end + 18, y), occ, font, _TITLE, 8)
    except Exception:  # exotic glyphs the embedded face can't shape
        logger.info("collage: title text skipped (unrenderable)")
    rule_y = y + 34 + 26
    draw.rectangle((_PAD, rule_y, _W - _PAD, rule_y + 2), fill=_RULE)
    draw.rectangle((_PAD, rule_y - 1, _PAD + 72, rule_y + 3), fill=_MINT)
    return rule_y + 3 + 44


# ---------------------------------------------------------------------------
# The card renderer (pure PIL)
# ---------------------------------------------------------------------------
def compose_lookbook(
    items: List[Tuple[str, Image.Image]], occasion: Optional[str] = None
) -> bytes:
    """Render the lookbook card: title band, hero garment band, finishing band.

    ``items`` are (slot, image) pairs; slots decide the band. Unknown slots
    join the finishing band. Bands are centered; either band may be empty.
    """
    hero = [(s, i) for s, i in items if s in _HERO_SLOTS]
    minor = [(s, i) for s, i in items if s not in _HERO_SLOTS]
    normalized = {id(i): _normalize_item(i) for _, i in items}

    inner = _W - 2 * _PAD
    hero_n = len(hero)
    hero_cell_w = (inner - (hero_n - 1) * _GUTTER) // hero_n if hero_n else 0

    # Height budget: title + bands actually present + outer margin.
    height = 0  # title measured on the real canvas below
    probe = Image.new("RGB", (_W, 10), _CANVAS)
    content_y = _title_band(probe, occasion)  # same math, measured cheaply
    height = content_y
    if hero_n:
        height += _HERO_H
    if minor:
        height += (_BAND_GAP if hero_n else 0) + _MINOR_H
    height += _PAD

    canvas = Image.new("RGB", (_W, height), _CANVAS)
    y = _title_band(canvas, occasion)

    if hero_n:
        for idx, (_slot, img) in enumerate(hero):
            cx = _PAD + idx * (hero_cell_w + _GUTTER) + hero_cell_w // 2
            _place(canvas, normalized[id(img)], cx, y + _HERO_H // 2,
                   hero_cell_w, _HERO_H)
        y += _HERO_H + (_BAND_GAP if minor else 0)

    if minor:
        row_w = len(minor) * _MINOR_W + (len(minor) - 1) * _MINOR_GAP
        x0 = (_W - row_w) // 2
        for idx, (_slot, img) in enumerate(minor):
            cx = x0 + idx * (_MINOR_W + _MINOR_GAP) + _MINOR_W // 2
            _place(canvas, normalized[id(img)], cx, y + _MINOR_H // 2,
                   _MINOR_W, _MINOR_H)

    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=_JPEG_QUALITY)
    return out.getvalue()


# ---------------------------------------------------------------------------
# Storage (per-user folder, content-addressed dedup) — seam for tests
# ---------------------------------------------------------------------------
def _store(user_id: UUID, data: bytes) -> Optional[str]:
    """Upload collage bytes exactly like every other derived image: through the
    image_blobs dedup, into a per-user folder. None when storage is missing."""
    try:
        from app.utils.supabase_storage import SupabaseStorageClient

        storage = SupabaseStorageClient.from_env()
    except Exception as exc:  # missing S3 env / client init failure
        logger.warning("collage: storage unavailable (%s)", type(exc).__name__)
        return None
    from app.utils.image_blob_store import get_or_upload

    return get_or_upload(
        data,
        lambda: storage.upload_bytes(
            data,
            folder=f"outfit_collages/{user_id}",
            content_type="image/jpeg",
            suffix=".jpg",
        ),
    )


def _ordered_slots(slots: Dict[str, ClothingItem]) -> List[Tuple[str, ClothingItem]]:
    order = _HERO_SLOTS + _MINOR_SLOTS
    known = [(s, slots[s]) for s in order if s in slots]
    extras = [(s, item) for s, item in slots.items() if s not in order]
    return known + extras


def get_or_create_outfit_collage(
    user_id: UUID,
    slots: Dict[str, ClothingItem],
    occasion: Optional[str] = None,
) -> Optional[str]:
    """Return the stored lookbook URL for this outfit, rendering it only on a
    cache miss. None whenever a decent card can't be made (best-effort)."""
    with_image = [(s, it) for s, it in _ordered_slots(slots) if it.image_url]
    if len(with_image) < _MIN_IMAGES:
        return None

    key = outfit_collage_key(user_id, [it for _, it in with_image], occasion)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    items: List[Tuple[str, Image.Image]] = []
    for slot, item in with_image:
        fetched = _download(item.image_url)
        if fetched is None:
            continue  # missing/unreachable item photo: skip the tile, keep going
        try:
            items.append((slot, Image.open(io.BytesIO(fetched[0])).convert("RGB")))
        except Exception:
            logger.info("collage: undecodable item image skipped (item=%s)", item.id)
    if len(items) < _MIN_IMAGES:
        return None

    url = _store(user_id, compose_lookbook(items, occasion))
    if url:
        _cache_put(key, url)
    return url
