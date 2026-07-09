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

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from app.models import ClothingItem
from app.models.closet import display_image_url

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


def _source_alpha(img: Image.Image) -> Optional[Image.Image]:
    """The image's own alpha channel iff it carries a REAL cutout (some
    transparency), else None. Prefer this over re-keying a JPEG."""
    if img.mode in ("RGBA", "LA"):
        alpha = img.getchannel("A")
    elif img.mode == "P" and "transparency" in img.info:
        alpha = img.convert("RGBA").getchannel("A")
    else:
        return None
    lo, _hi = alpha.getextrema()
    if lo >= 250:  # effectively opaque -> no usable cutout, fall back to key-out
        return None
    return alpha


def _background_mask(rgb: Image.Image) -> Optional[Image.Image]:
    """Content mask via BORDER-CONNECTED flood fill (255 = keep, 0 = background).

    The old approach keyed out EVERY near-background pixel globally, which also
    erased near-white regions INSIDE light garments (light denim, a white shoe) —
    punching holes. Here we only remove the contiguous near-background region that
    is REACHABLE FROM THE IMAGE BORDER: build a binary "near the border colour"
    map, frame it with a guaranteed-background 1px border so all edges connect,
    flood-fill that border region, and treat only the flooded pixels as background.
    Interior near-white islands are never reached, so they are preserved.

    Returns None when the border isn't a clean product-shot background (too little
    of it flooded) — the caller then keeps the photo as-is.
    """
    bg = _border_color(rgb)
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, bg))
    r, g, b = diff.split()
    dist = ImageChops.lighter(ImageChops.lighter(r, g), b)  # max channel delta
    # 255 where the pixel is within tolerance of the border colour (candidate bg).
    near_bg = dist.point(lambda v: 255 if v <= _KNOCK_TOL else 0)

    # Frame with a 1px all-background border so every edge segment is connected,
    # then flood the border-connected background from a corner to a marker (128).
    framed = ImageOps.expand(near_bg, border=1, fill=255)
    ImageDraw.floodfill(framed, (0, 0), 128, thresh=0)
    flooded = framed.crop((1, 1, 1 + rgb.width, 1 + rgb.height))

    # Keep everything that is NOT border-connected background (128). Interior
    # near-white islands stay 255 here, so they are kept as content.
    content = flooded.point(lambda v: 0 if v == 128 else 255)
    content = content.filter(ImageFilter.MedianFilter(5))  # despeckle

    removed = content.histogram()[0] / max(1, rgb.width * rgb.height)
    if removed < _MIN_BG_FRACTION:
        return None  # border colour didn't flood a real background -> keep as-is
    # Erode the mask edge ~1px so the anti-aliased background ring at the garment
    # edge is dropped (no light halo against the off-white canvas).
    return content.filter(ImageFilter.MinFilter(3))


def _normalize_item(
    img: Image.Image, canvas_bg: Tuple[int, int, int] = _CANVAS
) -> Tuple[Image.Image, Optional[Image.Image]]:
    """Cut the item out onto ``canvas_bg`` and trim to the content box. Returns
    (normalized RGB, content mask or None).

    Cutout source, in order of preference:
      1. the image's OWN alpha channel, if it carries a real cutout;
      2. a BORDER-CONNECTED flood fill of the near-background (see
         :func:`_background_mask`) — which, unlike a global colour key, never
         removes near-white regions INSIDE a light garment;
      3. otherwise the photo is kept as a plain rectangle (honest fallback for a
         non-product-shot / borderless source).

    ``canvas_bg`` is the field the cutout will sit on — flattening the feathered
    edge to the SAME colour as the destination keeps the soft edge seamless.
    """
    alpha = _source_alpha(img)
    rgb = img.convert("RGB")

    if alpha is not None:
        content = alpha.point(lambda v: 255 if v > 16 else 0)
        content = content.filter(ImageFilter.MinFilter(3))  # trim halo
    else:
        content = _background_mask(rgb)
        if content is None:
            return rgb, None  # borderless / busy: no reliable background to unify

    feather = content.filter(ImageFilter.GaussianBlur(2))
    flat = Image.new("RGB", rgb.size, canvas_bg)
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


def _fit(
    size: Tuple[int, int], cell_w: int, cell_h: int, fill: float = _FILL
) -> Tuple[int, int]:
    """Scale to fill ``fill`` of the cell (long-edge / bounding-box fit, aspect
    preserved), bounded upscaling."""
    w, h = size
    scale = min(fill * cell_w / w, fill * cell_h / h, _MAX_UPSCALE)
    return max(1, int(w * scale)), max(1, int(h * scale))


def _place(
    canvas: Image.Image,
    item: Tuple[Image.Image, Optional[Image.Image]],
    cx: int, cy: int, cell_w: int, cell_h: int,
    fill: float = _FILL,
) -> None:
    """Center one normalized item in its cell with a soft contact shadow."""
    flat, mask = item
    w, h = _fit(flat.size, cell_w, cell_h, fill)
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
    # G6: usable_image_url masks an on-model crop, so a person is never composited here.
    with_image = [(s, it) for s, it in _ordered_slots(slots) if usable_image_url(it)]
    if len(with_image) < _MIN_IMAGES:
        return None

    key = outfit_collage_key(user_id, [it for _, it in with_image], occasion)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    items: List[Tuple[str, Image.Image]] = []
    for slot, item in with_image:
        fetched = _download(usable_image_url(item))
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


# ===========================================================================
# Today's Look GRID variant (Wave: Today's Look)
# ---------------------------------------------------------------------------
# A DIFFERENT card from the editorial lookbook above: every item of the day's
# outfit knocked out on ONE warm off-white field, equal cells, side by side — no
# hero/finishing bands, no title band. It reuses the same knockout + placement
# spine (_normalize_item / _place) and the same content-addressed store, so it
# inherits the dedup and the "never break compose" failure posture.
#
# Two rules the editorial card doesn't have, both from the Today's Look spec:
#   * every outfit slot gets a cell — an item WITHOUT a usable image renders a
#     neutral placeholder tile, it is NEVER skipped (so the grid always mirrors
#     the composed outfit one-to-one);
#   * the background is a CLEARLY warm off-white (#F3EEE6) — visibly warmer than
#     the near-white porcelain, tonal with the app's page bg (#EEEDE9) but a shade
#     lighter so cutouts still pop (grid-v5).
#   * items are HEIGHT-NORMALIZED: each is scaled to a shared target height
#     (~78% of the canvas) on a common vertical centre line with even gutters, so
#     the row reads as one balanced product grid — not scattered/floating tiles.
#   * canvas is 1080x540 (2:1) matching the Home card's image container.
# ===========================================================================
_GRID_LAYOUT_VERSION = "grid-v5"
_GRID_W = 1080
_GRID_H = 540                  # 2:1 canvas (was 1080x720)
_GRID_GUTTER = 40              # even gutter between the height-normalized items
_GRID_FILL = 0.90              # the row occupies up to this fraction of canvas width
_GRID_TARGET_H_FRAC = 0.78     # each item scaled to ~78% of the canvas height
# Clearly warm off-white — visibly differs from white; tonal with the app page bg.
_GRID_BG = (243, 238, 230)     # #F3EEE6
_GRID_PLACEHOLDER = (233, 228, 219)  # neutral tile (a touch darker than the bg)
_GRID_PLACEHOLDER_AR = 0.72    # placeholder panel width:height (portrait tile)

# Usable image = a real, resolved photo. A generated card that is still a raw
# crop (pending_retry / failed) or an explicit placeholder / pending status is
# NOT usable and renders as a neutral tile. resolved / ready / user_uploaded and
# untagged manual items all pass — this is the inclusive reading of the spec's
# "generation_status='ready' OR image_status='resolved'" that still keeps a real
# user-uploaded photo (image_status='user_uploaded') on the card.
_UNUSABLE_IMAGE_STATUS = frozenset({"placeholder", "pending"})
_UNUSABLE_GEN_STATUS = frozenset({"failed", "pending_retry"})


def usable_image_url(item: ClothingItem) -> Optional[str]:
    """The item's image_url iff it points at a real, showable photo — else None.

    G6: goes through display_image_url first, so an ON-MODEL crop (a person) is NEVER
    composited into a collage until a verified person-free card lands. A masked item drops
    out of the collage AND changes the cache key, so a later self-heal re-renders it in."""
    url = display_image_url(item)
    if not url:
        return None
    if (getattr(item, "image_status", None) or "") in _UNUSABLE_IMAGE_STATUS:
        return None
    if (getattr(item, "generation_status", None) or "") in _UNUSABLE_GEN_STATUS:
        return None
    return url


def _grid_key(user_id: UUID, ordered: List[Tuple[str, ClothingItem]]) -> str:
    """Order-sensitive hash of the ordered (id, usable-url-or-blank) pairs — a
    missing image is part of the key so a later heal invalidates the card."""
    pairs = [f"{it.id}:{usable_image_url(it) or ''}" for _, it in ordered]
    head = [_GRID_LAYOUT_VERSION, str(user_id)]
    return hashlib.sha256("|".join(head + pairs).encode()).hexdigest()


def _placeholder_tile(w: int, h: int) -> Tuple[Image.Image, Image.Image]:
    """A quiet neutral rounded tile (image, mask) for an item with no usable
    photo — height-normalized like a real item so the row stays even."""
    tile = Image.new("RGB", (w, h), _GRID_PLACEHOLDER)
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    try:
        draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=28, fill=255)
    except AttributeError:  # Pillow < 8.2
        draw.rectangle((0, 0, w - 1, h - 1), fill=255)
    return tile, mask


def _paste_item(
    canvas: Image.Image, flat: Image.Image, mask: Optional[Image.Image], x: int, y: int
) -> None:
    """Paste one prepared item at (x, y) with a soft contact shadow (masked items)."""
    if mask is not None:
        shadow = mask.filter(ImageFilter.GaussianBlur(12)).point(lambda v: v * 10 // 100)
        canvas.paste((203, 200, 194), (x, y + 10), shadow)  # grounded, 10% depth
        canvas.paste(flat, (x, y), mask.filter(ImageFilter.GaussianBlur(2)))
    else:
        canvas.paste(flat, (x, y))


def compose_grid(cells: List[Optional[Image.Image]]) -> bytes:
    """Render N items in one balanced, height-normalized row on a warm off-white
    (#F3EEE6) 1080x540 field. Each item (or a neutral placeholder for a missing
    photo — never dropped) is scaled to a SHARED target height (~78% of the
    canvas), aspect preserved, aligned on a common vertical centre line with even
    gutters; the whole row is shrunk to fit and centred. No bands, no title."""
    n = max(1, len(cells))
    target_h = int(_GRID_TARGET_H_FRAC * _GRID_H)

    # Prepare each item at the shared target height (aspect preserved).
    prepared: List[Tuple[Image.Image, Optional[Image.Image], int, int]] = []
    for img in cells:
        if img is None:
            w = max(1, int(target_h * _GRID_PLACEHOLDER_AR))
            tile, mask = _placeholder_tile(w, target_h)
            prepared.append((tile, mask, w, target_h))
            continue
        flat, mask = _normalize_item(img, _GRID_BG)
        scale = target_h / max(1, flat.height)
        w = max(1, int(flat.width * scale))
        flat = flat.resize((w, target_h), Image.LANCZOS)
        mask = mask.resize((w, target_h), Image.LANCZOS) if mask is not None else None
        prepared.append((flat, mask, w, target_h))

    # Shrink the row uniformly if it would exceed the allowed width.
    gutters = _GRID_GUTTER * (n - 1)
    row_w = sum(p[2] for p in prepared) + gutters
    avail = int(_GRID_FILL * _GRID_W)
    if row_w > avail:
        shrink = (avail - gutters) / max(1, row_w - gutters)
        resized: List[Tuple[Image.Image, Optional[Image.Image], int, int]] = []
        for flat, mask, w, h in prepared:
            nw, nh = max(1, int(w * shrink)), max(1, int(h * shrink))
            flat = flat.resize((nw, nh), Image.LANCZOS)
            mask = mask.resize((nw, nh), Image.LANCZOS) if mask is not None else None
            resized.append((flat, mask, nw, nh))
        prepared = resized
        row_w = sum(p[2] for p in prepared) + gutters

    canvas = Image.new("RGB", (_GRID_W, _GRID_H), _GRID_BG)
    cy = _GRID_H // 2
    x = (_GRID_W - row_w) // 2  # centre the whole row
    for flat, mask, w, h in prepared:
        _paste_item(canvas, flat, mask, x, cy - h // 2)  # common centre line
        x += w + _GRID_GUTTER

    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=_JPEG_QUALITY)
    return out.getvalue()


def get_or_create_grid_collage(
    user_id: UUID,
    slots: Dict[str, ClothingItem],
    *,
    no_persist: bool = False,
) -> Optional[str]:
    """Stored URL of the warm off-white side-by-side grid for this outfit, rendered
    only on a cache miss. Every slot becomes an item (missing image -> placeholder).

    Returns None when there is nothing to render at all (no slots, or not a single
    item image could be fetched/decoded — the caller then falls back to its own
    client-side tile grid), or in incognito (``no_persist`` leaves no storage
    trace). Best-effort throughout: never raises into the composer/route."""
    ordered = _ordered_slots(slots)
    if not ordered:
        return None

    key = _grid_key(user_id, ordered)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    cells: List[Optional[Image.Image]] = []
    any_real = False
    for _slot, item in ordered:
        url = usable_image_url(item)
        img: Optional[Image.Image] = None
        if url:
            fetched = _download(url)
            if fetched is not None:
                try:
                    # Do NOT force RGB here: keep any real alpha cutout so
                    # _normalize_item can prefer it over re-keying the JPEG.
                    img = Image.open(io.BytesIO(fetched[0]))
                    img.load()
                    any_real = True
                except Exception:
                    logger.info("grid collage: undecodable image (item=%s)", item.id)
                    img = None
        cells.append(img)

    # A grid of only placeholders adds nothing over the client fallback.
    if not any_real:
        return None
    if no_persist:
        return None

    url = _store(user_id, compose_grid(cells))
    if url:
        _cache_put(key, url)
    return url
