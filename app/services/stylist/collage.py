"""Outfit collages, v2 (Collage Phase 2): composed from STORED TRUE-ALPHA
CUTOUTS — the render-time color key is GONE.

WHY V2 (the Phase-0 spike, COLLAGE_QUALITY_SPIKE.md): v1 re-derived a cutout at
every render with a border-flood color key. On this closet — near-white product
shots, many white/light garments — that key structurally cannot work: it ate
bites out of light jeans, dissolved white tees, left baked-in shadows floating
as smudges, and pasted opaque mismatched rectangles when it gave up. Phase 1
moved matting to image-birth: every item now carries cutout_url/cutout_status —
a u2net matte, QA-gated, stored once. This module just COMPOSITES:

  * cutout_status='ready'  -> the stored RGBA is downloaded and its own alpha
    channel is the mask (the _source_alpha path, finally load-bearing). No key,
    no flood fill, no per-render pixel guessing.
  * 'no_matte' / NULL / cutout download failure -> the display image renders
    FLAT: a quiet rounded tile with the photo as-is. Honest and graceful —
    NEVER the old patchy color-key rectangle, never a shredded garment.
  * no usable image at all -> the neutral placeholder tile (grid only; the
    lookbook simply skips the slot as before).

Composition rules (both renderers):
  * CATEGORY-AWARE SCALE — the grid scales each item by its slot (a sneaker is
    ~36% of canvas height, not a shirt's 82%; see _GRID_SCALE) and BASELINE-
    ANCHORS footwear/accessories low so the row reads as an outfit, not tiles.
    The lookbook keeps its hero/finishing band hierarchy.
  * ONE SYNTHETIC SHADOW — every visible cell gets the same soft drop shadow
    derived from its mask (unified direction, slightly right + down). Baked
    source shadows were removed by the matte; this is the only grounding.

STAYS PURE: PIL/numpy-free compositing on already-stored images — NO generation
API call ever happens here (a per-collage generation was evaluated and rejected
in the spike for recurring cost), and a render stays well under a second.

CACHING — same two-layer contract as v1, keys bumped (grid-v6 / lookbook-v3) so
every pre-v2 card re-renders, and the cutout_url is folded into the keys so a
re-matte invalidates:
  * in-process LRU keyed by sha256(layout version + occasion + user + sorted
    "id:image_url:cutout_url" pairs);
  * uploads go through the content-addressed image_blobs dedup — the renderer
    is deterministic, so identical inputs converge to one stored object.

FAILURE POSTURE — unchanged: items without an image url and images that fail to
download/decode are skipped; fewer than 2 usable images (lookbook), or any
storage failure, yields None. Missing fonts (Pillow < 10.1) just drop the title
band. Nothing here may ever break compose_outfit or Today's Look.
"""
from __future__ import annotations

import hashlib
import io
import logging
import threading
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.models import ClothingItem
from app.models.closet import display_image_url

# Reused download seam (module attr so tests monkeypatch collage._download).
from app.photo_closet.generation_service import _download_bytes as _download

logger = logging.getLogger(__name__)

# --- Palette (porcelain field, editorial neutrals, one mint accent) ----------
_CANVAS = (250, 249, 247)   # porcelain: lookbook field, warm not clinical
_EYEBROW = (138, 133, 124)  # taupe tracked caps
_TITLE = (42, 42, 40)       # charcoal occasion text
_RULE = (229, 226, 220)     # hairline
_MINT = (75, 226, 214)      # app accent --mint (#4be2d6)

# --- Lookbook geometry --------------------------------------------------------
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
_TRIM_MARGIN = 0.03       # breathing room kept around a cutout's alpha bbox

_MIN_IMAGES = 2           # a 1-tile card adds nothing over the item thumbnail

_LAYOUT_VERSION = "lookbook-v3"

# Hero band = the garments that make the silhouette; finishing band = the rest.
_HERO_SLOTS = ("top", "dress", "bottom", "outerwear")
_MINOR_SLOTS = ("footwear", "accessory")

# --- The one synthetic shadow (every visible cell, both renderers) -----------
_SHADOW_BLUR = 14
_SHADOW_OFFSET = (4, 14)          # unified direction: slightly right, mostly down
_SHADOW_OPACITY = 16              # percent
_SHADOW_COLOR = (196, 191, 182)   # warm grey, tonal with both canvases

_TILE_RADIUS = 28                 # rounded corner of flat/placeholder tiles

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


def _item_key_pair(item) -> str:
    """One item's cache-key atom: id + display image + cutout. The cutout_url is
    part of the key so a re-matte (or a first matte landing after a render)
    invalidates the cached card."""
    return (
        f"{item.id}:{getattr(item, 'image_url', None)}"
        f":{getattr(item, 'cutout_url', None) or ''}"
    )


def outfit_collage_key(
    user_id: UUID, items: List[ClothingItem], occasion: Optional[str] = None
) -> str:
    """Item-SET hash: sorted "id:image_url:cutout_url" pairs + user + layout
    version + occasion (it is drawn on the card). Order-insensitive."""
    pairs = sorted(_item_key_pair(item) for item in items)
    head = [_LAYOUT_VERSION, f"occ={_norm_occasion(occasion)}", str(user_id)]
    return hashlib.sha256("|".join(head + pairs).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Cutout plumbing: stored alpha in, prepared cell out. NO COLOR KEY.
# ---------------------------------------------------------------------------
def _source_alpha(img: Image.Image) -> Optional[Image.Image]:
    """The image's own alpha channel iff it carries a REAL cutout (some
    transparency), else None. This is the v2 router: a stored Phase-1 matte has
    real alpha and composites as a cutout; an opaque display JPEG renders as a
    flat tile. Nothing is ever keyed out at render time."""
    if img.mode in ("RGBA", "LA"):
        alpha = img.getchannel("A")
    elif img.mode == "P" and "transparency" in img.info:
        alpha = img.convert("RGBA").getchannel("A")
    else:
        return None
    lo, _hi = alpha.getextrema()
    if lo >= 250:  # effectively opaque -> not a cutout
        return None
    return alpha


def _trim_to_alpha(rgb: Image.Image, alpha: Image.Image) -> Tuple[Image.Image, Image.Image]:
    """Crop a cutout to its alpha bbox plus a small margin, so scaling is by
    GARMENT size, not by however much empty field the source carried."""
    box = alpha.getbbox()
    if not box:
        return rgb, alpha
    mx = int(max(box[2] - box[0], box[3] - box[1]) * _TRIM_MARGIN)
    box = (
        max(0, box[0] - mx),
        max(0, box[1] - mx),
        min(rgb.width, box[2] + mx),
        min(rgb.height, box[3] + mx),
    )
    return rgb.crop(box), alpha.crop(box)


def _prepare_cell(img: Image.Image) -> Tuple[Image.Image, Image.Image, bool]:
    """One downloaded image -> (rgb, mask, is_cutout).

    A stored matte (real alpha) becomes a trimmed cutout with its own alpha as
    the mask. Anything opaque becomes a FLAT rounded tile — the graceful v2
    fallback for no_matte / not-yet-matted items. Never a color key."""
    alpha = _source_alpha(img)
    rgb = img.convert("RGB")
    if alpha is not None:
        rgb, alpha = _trim_to_alpha(rgb, alpha)
        return rgb, alpha, True
    mask = Image.new("L", rgb.size, 0)
    draw = ImageDraw.Draw(mask)
    try:
        draw.rounded_rectangle(
            (0, 0, rgb.width - 1, rgb.height - 1), radius=_TILE_RADIUS, fill=255
        )
    except AttributeError:  # Pillow < 8.2
        draw.rectangle((0, 0, rgb.width - 1, rgb.height - 1), fill=255)
    return rgb, mask, False


def _fit(
    size: Tuple[int, int], cell_w: int, cell_h: int, fill: float = _FILL
) -> Tuple[int, int]:
    """Scale to fill ``fill`` of the cell (long-edge / bounding-box fit, aspect
    preserved), bounded upscaling."""
    w, h = size
    scale = min(fill * cell_w / w, fill * cell_h / h, _MAX_UPSCALE)
    return max(1, int(w * scale)), max(1, int(h * scale))


def _paste_with_shadow(
    canvas: Image.Image, rgb: Image.Image, mask: Image.Image, x: int, y: int
) -> None:
    """THE one synthetic shadow + the paste. Same blur, offset, direction and
    depth for every item on every card — items sit on the canvas instead of
    floating, with none of the old baked-shadow smudges."""
    shadow = mask.filter(ImageFilter.GaussianBlur(_SHADOW_BLUR)).point(
        lambda v: v * _SHADOW_OPACITY // 100
    )
    canvas.paste(_SHADOW_COLOR, (x + _SHADOW_OFFSET[0], y + _SHADOW_OFFSET[1]), shadow)
    canvas.paste(rgb, (x, y), mask)


def _place(
    canvas: Image.Image,
    prepared: Tuple[Image.Image, Image.Image, bool],
    cx: int, cy: int, cell_w: int, cell_h: int,
    fill: float = _FILL,
) -> None:
    """Center one prepared cell (cutout or flat tile) in a lookbook band cell."""
    rgb, mask, _is_cutout = prepared
    w, h = _fit(rgb.size, cell_w, cell_h, fill)
    rgb = rgb.resize((w, h), Image.LANCZOS)
    mask = mask.resize((w, h), Image.LANCZOS)
    _paste_with_shadow(canvas, rgb, mask, cx - w // 2, cy - h // 2)


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
# The lookbook card renderer (pure PIL)
# ---------------------------------------------------------------------------
def compose_lookbook(
    items: List[Tuple[str, Image.Image]], occasion: Optional[str] = None
) -> bytes:
    """Render the lookbook card: title band, hero garment band, finishing band.

    ``items`` are (slot, image) pairs; slots decide the band. An image with real
    alpha (a stored Phase-1 matte) composites as a cutout; an opaque image
    renders as a flat rounded tile. Bands are centered; either may be empty.
    """
    hero = [(s, i) for s, i in items if s in _HERO_SLOTS]
    minor = [(s, i) for s, i in items if s not in _HERO_SLOTS]
    prepared = {id(i): _prepare_cell(i) for _, i in items}

    inner = _W - 2 * _PAD
    hero_n = len(hero)
    hero_cell_w = (inner - (hero_n - 1) * _GUTTER) // hero_n if hero_n else 0

    # Height budget: title + bands actually present + outer margin.
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
            _place(canvas, prepared[id(img)], cx, y + _HERO_H // 2,
                   hero_cell_w, _HERO_H)
        y += _HERO_H + (_BAND_GAP if minor else 0)

    if minor:
        row_w = len(minor) * _MINOR_W + (len(minor) - 1) * _MINOR_GAP
        x0 = (_W - row_w) // 2
        for idx, (_slot, img) in enumerate(minor):
            cx = x0 + idx * (_MINOR_W + _MINOR_GAP) + _MINOR_W // 2
            _place(canvas, prepared[id(img)], cx, y + _MINOR_H // 2,
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


def _fetch_item_image(item) -> Optional[Image.Image]:
    """Download the item's best composable image: the stored Phase-1 cutout when
    the item is matted (RGBA, real alpha -> composites as a cutout), else the
    display image (opaque -> renders as a flat tile). The display gate stays
    supreme: a masked item (usable_image_url None) is never fetched at all, even
    if an old cutout exists. Cutout download failure falls back to flat."""
    display_url = usable_image_url(item)
    if not display_url:
        return None
    urls = []
    if getattr(item, "cutout_status", None) == "ready" and getattr(item, "cutout_url", None):
        urls.append(item.cutout_url)
    urls.append(display_url)
    for url in urls:
        fetched = _download(url)
        if fetched is None:
            continue
        try:
            img = Image.open(io.BytesIO(fetched[0]))
            img.load()  # keep native mode: the cutout's alpha IS the mask
            return img
        except Exception:
            logger.info("collage: undecodable image skipped (item=%s)", item.id)
    return None


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
        img = _fetch_item_image(item)
        if img is None:
            continue  # missing/unreachable item photo: skip the tile, keep going
        items.append((slot, img))
    if len(items) < _MIN_IMAGES:
        return None

    url = _store(user_id, compose_lookbook(items, occasion))
    if url:
        _cache_put(key, url)
    return url


# ===========================================================================
# Today's Look GRID variant, v2 (grid-v6)
# ---------------------------------------------------------------------------
# A DIFFERENT card from the editorial lookbook above: the day's outfit on ONE
# warm off-white field — no hero/finishing bands, no title band. v2 rules:
#   * every outfit slot gets a cell — an item WITHOUT a usable image renders a
#     neutral placeholder tile, it is NEVER skipped (the grid always mirrors
#     the composed outfit one-to-one);
#   * CATEGORY-AWARE SCALE (_GRID_SCALE): garments at their natural visual
#     height, footwear ~36%, accessories ~28% — a sneaker no longer renders as
#     tall as a shirt;
#   * BASELINE ANCHORING (_GRID_ANCHOR): garments sit on the canvas midline;
#     footwear/accessories are anchored LOW, where they'd sit under an outfit;
#   * canvas 1080x540 (2:1) on the clearly-warm off-white (#F3EEE6), matching
#     the Home card's image container.
# ===========================================================================
_GRID_LAYOUT_VERSION = "grid-v6"
_GRID_W = 1080
_GRID_H = 540                  # 2:1 canvas
_GRID_GUTTER = 44              # even gutter between items
_GRID_FILL = 0.92              # the row occupies up to this fraction of canvas width
# Clearly warm off-white — visibly differs from white; tonal with the app page bg.
_GRID_BG = (243, 238, 230)     # #F3EEE6
_GRID_PLACEHOLDER = (233, 228, 219)  # neutral tile (a touch darker than the bg)
_GRID_PLACEHOLDER_AR = 0.72    # placeholder panel width:height (portrait tile)

# Category scale table (the tuning knob): target item height as a fraction of
# the canvas. Real-world visual hierarchy — shoes are small, coats are long.
_GRID_SCALE = {
    "top": 0.66,
    "bottom": 0.82,
    "dress": 0.86,
    "outerwear": 0.84,
    "footwear": 0.36,
    "accessory": 0.28,
}
_GRID_SCALE_DEFAULT = 0.60     # unknown slots: modest garment-ish presence

# Vertical anchors: fraction of canvas height where the item's BOTTOM edge
# sits. Slots not listed here are centered on the canvas midline.
_GRID_ANCHOR = {
    "footwear": 0.86,
    "accessory": 0.80,
}

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
    """Order-sensitive hash of the ordered (id, usable-url, cutout-url) pairs —
    a missing image and a later-landing matte are both part of the key, so a
    heal or a fresh cutout invalidates the card."""
    pairs = [
        f"{it.id}:{usable_image_url(it) or ''}:{getattr(it, 'cutout_url', None) or ''}"
        for _, it in ordered
    ]
    head = [_GRID_LAYOUT_VERSION, str(user_id)]
    return hashlib.sha256("|".join(head + pairs).encode()).hexdigest()


def _grid_target_h(slot: str) -> int:
    return int(_GRID_SCALE.get(slot, _GRID_SCALE_DEFAULT) * _GRID_H)


def _placeholder_cell(slot: str) -> Tuple[Image.Image, Image.Image]:
    """A quiet neutral rounded tile (image, mask) for an item with no usable
    photo — sized by its slot like a real item so the row stays balanced."""
    h = _grid_target_h(slot)
    w = max(1, int(h * _GRID_PLACEHOLDER_AR))
    tile = Image.new("RGB", (w, h), _GRID_PLACEHOLDER)
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    try:
        draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=_TILE_RADIUS, fill=255)
    except AttributeError:  # Pillow < 8.2
        draw.rectangle((0, 0, w - 1, h - 1), fill=255)
    return tile, mask


def compose_grid(cells: List[Tuple[str, Optional[Image.Image]]]) -> bytes:
    """Render the day's outfit on the warm off-white 1080x540 field.

    ``cells`` are (slot, image) pairs in display order. Images with real alpha
    (stored mattes) composite as cutouts; opaque images render as flat rounded
    tiles; None renders the neutral placeholder. Each cell is scaled by its
    slot's category height and anchored per the slot (garments on the midline,
    footwear/accessories seated low), the whole row shrunk-to-fit and centred.
    """
    # Prepare each cell at its category target height (aspect preserved).
    prepared: List[Tuple[Image.Image, Image.Image, str]] = []
    for slot, img in cells:
        if img is None:
            tile, mask = _placeholder_cell(slot)
            prepared.append((tile, mask, slot))
            continue
        rgb, mask, _is_cutout = _prepare_cell(img)
        th = _grid_target_h(slot)
        scale = min(th / max(1, rgb.height), _MAX_UPSCALE)
        w, h = max(1, int(rgb.width * scale)), max(1, int(rgb.height * scale))
        rgb = rgb.resize((w, h), Image.LANCZOS)
        mask = mask.resize((w, h), Image.LANCZOS)
        prepared.append((rgb, mask, slot))

    # Shrink the row uniformly if it would exceed the allowed width.
    n = max(1, len(prepared))
    gutters = _GRID_GUTTER * (n - 1)
    row_w = sum(p[0].width for p in prepared) + gutters
    avail = int(_GRID_FILL * _GRID_W)
    if row_w > avail:
        shrink = (avail - gutters) / max(1, row_w - gutters)
        resized = []
        for rgb, mask, slot in prepared:
            nw = max(1, int(rgb.width * shrink))
            nh = max(1, int(rgb.height * shrink))
            resized.append((rgb.resize((nw, nh), Image.LANCZOS),
                            mask.resize((nw, nh), Image.LANCZOS), slot))
        prepared = resized
        row_w = sum(p[0].width for p in prepared) + gutters

    canvas = Image.new("RGB", (_GRID_W, _GRID_H), _GRID_BG)
    x = (_GRID_W - row_w) // 2  # centre the whole row
    for rgb, mask, slot in prepared:
        if slot in _GRID_ANCHOR:
            y = int(_GRID_ANCHOR[slot] * _GRID_H) - rgb.height  # baseline: bottom edge
        else:
            y = (_GRID_H - rgb.height) // 2                     # garment midline
        y = max(0, min(y, _GRID_H - rgb.height))
        _paste_with_shadow(canvas, rgb, mask, x, y)
        x += rgb.width + _GRID_GUTTER

    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=_JPEG_QUALITY)
    return out.getvalue()


def get_or_create_grid_collage(
    user_id: UUID,
    slots: Dict[str, ClothingItem],
    *,
    no_persist: bool = False,
) -> Optional[str]:
    """Stored URL of the warm off-white grid for this outfit, rendered only on a
    cache miss. Every slot becomes a cell (missing image -> placeholder).

    Returns None when there is nothing to render at all (no slots, or not a
    single item image could be fetched/decoded — the caller then falls back to
    its own client-side tile grid), or in incognito (``no_persist`` leaves no
    storage trace). Best-effort throughout: never raises into the composer/route."""
    ordered = _ordered_slots(slots)
    if not ordered:
        return None

    key = _grid_key(user_id, ordered)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    cells: List[Tuple[str, Optional[Image.Image]]] = []
    any_real = False
    for slot, item in ordered:
        img = _fetch_item_image(item)
        if img is not None:
            any_real = True
        cells.append((slot, img))

    # A grid of only placeholders adds nothing over the client fallback.
    if not any_real:
        return None
    if no_persist:
        return None

    url = _store(user_id, compose_grid(cells))
    if url:
        _cache_put(key, url)
    return url
