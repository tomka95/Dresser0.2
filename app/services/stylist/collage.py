"""Outfit collage (Wave S3): ONE lookbook-style review image tiled from the
composed outfit's own item photos. Pure PIL on already-stored cutouts — no
generation API, no model, no new pixels invented.

LAYOUT — a near-square grid (cols = ceil(sqrt(n))) of fixed square cells on the
same light neutral the cutout cards use, consistent padding everywhere, each
item photo fit-contained and centered in its cell; a short last row is centered
so 3 or 5 items still read as a balanced lookbook page, not a ragged grid.

CACHING — two layers:
  * an in-process LRU keyed by sha256(user + sorted "id:image_url" pairs), so
    the same item COMBINATION is never re-downloaded/re-tiled while the server
    lives (the key includes image urls, so a re-ingested item photo invalidates
    naturally);
  * the upload itself goes through the content-addressed image_blobs dedup —
    tiling is deterministic for the same inputs, so even across restarts an
    identical collage converges to the one stored object instead of a new blob.

FAILURE POSTURE — strictly best-effort. Items without an image url and images
that fail to download/decode are skipped; fewer than 2 usable images, or any
storage failure, yields None and the outfit ships without a collage. Nothing
here may ever break compose_outfit.
"""
from __future__ import annotations

import hashlib
import io
import logging
import math
import threading
from collections import OrderedDict
from typing import Dict, List, Optional
from uuid import UUID

from PIL import Image

from app.models import ClothingItem

# Reused download seam (module attr so tests monkeypatch collage._download).
from app.photo_closet.generation_service import _download_bytes as _download

logger = logging.getLogger(__name__)

_CELL = 512           # square cell edge, px
_PAD = 24             # uniform gutter: outer margin AND inter-cell spacing
_BG = (242, 242, 242)  # matches cutout.py's neutral card background
_JPEG_QUALITY = 90
_MIN_IMAGES = 2       # a 1-tile "collage" adds nothing over the item thumbnail

# Visual reading order for the tiles, independent of anchor insertion order.
_SLOT_ORDER = ("top", "dress", "bottom", "outerwear", "footwear", "accessory")

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


def outfit_collage_key(user_id: UUID, items: List[ClothingItem]) -> str:
    """Item-SET hash: sorted "id:image_url" pairs + user. Order-insensitive, so
    the same combination composed twice (whatever the slot fill order) hits."""
    pairs = sorted(f"{item.id}:{item.image_url}" for item in items)
    return hashlib.sha256("|".join([str(user_id)] + pairs).encode()).hexdigest()


# ---------------------------------------------------------------------------
# The grid tiler (pure PIL)
# ---------------------------------------------------------------------------
def compose_collage(images: List[Image.Image]) -> bytes:
    """Tile ``images`` into one balanced grid on a neutral background (JPEG).

    cols = ceil(sqrt(n)) keeps the grid near-square (2 -> 2x1, 3/4 -> 2x2,
    5 -> 3x2); a short last row is horizontally centered. Each image keeps its
    aspect ratio inside its cell.
    """
    n = len(images)
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    canvas = Image.new(
        "RGB",
        (cols * _CELL + (cols + 1) * _PAD, rows * _CELL + (rows + 1) * _PAD),
        _BG,
    )
    for idx, img in enumerate(images):
        row, col = divmod(idx, cols)
        in_row = min(n - row * cols, cols)
        row_shift = (cols - in_row) * (_CELL + _PAD) // 2  # center a short row
        tile = img.convert("RGB")
        tile.thumbnail((_CELL, _CELL), Image.LANCZOS)
        x = _PAD + col * (_CELL + _PAD) + row_shift + (_CELL - tile.width) // 2
        y = _PAD + row * (_CELL + _PAD) + (_CELL - tile.height) // 2
        canvas.paste(tile, (x, y))
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


def _ordered_items(slots: Dict[str, ClothingItem]) -> List[ClothingItem]:
    known = [slots[s] for s in _SLOT_ORDER if s in slots]
    extras = [item for slot, item in slots.items() if slot not in _SLOT_ORDER]
    return known + extras


def get_or_create_outfit_collage(
    user_id: UUID, slots: Dict[str, ClothingItem]
) -> Optional[str]:
    """Return the stored collage URL for this outfit, tiling it only on a cache
    miss. None whenever a decent collage can't be made (best-effort contract).
    """
    with_image = [it for it in _ordered_items(slots) if it.image_url]
    if len(with_image) < _MIN_IMAGES:
        return None

    key = outfit_collage_key(user_id, with_image)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    images: List[Image.Image] = []
    for item in with_image:
        fetched = _download(item.image_url)
        if fetched is None:
            continue  # missing/unreachable item photo: skip the tile, keep going
        try:
            images.append(Image.open(io.BytesIO(fetched[0])).convert("RGB"))
        except Exception:
            logger.info("collage: undecodable item image skipped (item=%s)", item.id)
    if len(images) < _MIN_IMAGES:
        return None

    url = _store(user_id, compose_collage(images))
    if url:
        _cache_put(key, url)
    return url
