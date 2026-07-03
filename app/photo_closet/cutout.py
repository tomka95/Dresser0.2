"""Per-garment cutout from a photo (Wave 1).

Given the original (already-sanitized) photo and one garment's ``box_2d`` (+ optional
mask), produce a clean card image:

  * mask present + reliable -> alpha-composite the masked garment onto a NEUTRAL
    background, so the card shows the garment isolated.
  * otherwise -> the rectangular box crop (the dependable fallback).

No external segmentation model and no generation — this is pure PIL on pixels the user
already uploaded. The result is uploaded through the content-addressed image_blobs
dedup, exactly like every other ingest image.
"""
from __future__ import annotations

import base64
import binascii
import io
import logging
from dataclasses import dataclass
from typing import List, Optional

from PIL import Image

logger = logging.getLogger(__name__)

# Card background for masked cutouts — a light neutral, matching the deck's panels.
_NEUTRAL_BG = (242, 242, 242)
# A mask is "reliable" only if it actually segments something: not near-empty and not
# near-full (both mean the model gave us no useful boundary -> use the box crop).
_MASK_MIN_FRACTION = 0.02
_MASK_MAX_FRACTION = 0.98


@dataclass(frozen=True)
class Cutout:
    data: bytes
    suffix: str
    content_type: str
    used_mask: bool


def _box_to_pixels(box_2d: List[int], width: int, height: int):
    """Map [ymin,xmin,ymax,xmax] (0..1000) to clamped pixel (x0,y0,x1,y1) or None."""
    if not box_2d or len(box_2d) != 4:
        return None
    ymin, xmin, ymax, xmax = box_2d
    x0 = max(0, min(width, round(xmin / 1000 * width)))
    y0 = max(0, min(height, round(ymin / 1000 * height)))
    x1 = max(0, min(width, round(xmax / 1000 * width)))
    y1 = max(0, min(height, round(ymax / 1000 * height)))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    return x0, y0, x1, y1


def _decode_mask(mask_b64: str, size) -> Optional[Image.Image]:
    """Decode a base64 PNG mask to an 'L' image resized to ``size`` (the box), or None.

    Accepts a bare base64 string or a ``data:image/png;base64,...`` data URL.
    """
    s = mask_b64.strip()
    if s.startswith("data:"):
        comma = s.find(",")
        if comma == -1:
            return None
        s = s[comma + 1:]
    try:
        raw = base64.b64decode(s, validate=False)
        m = Image.open(io.BytesIO(raw)).convert("L")
    except (binascii.Error, ValueError, OSError):
        return None
    if m.size != size:
        m = m.resize(size, Image.BILINEAR)
    return m


def _mask_is_reliable(mask: Image.Image) -> bool:
    hist = mask.histogram()  # 256 buckets
    total = sum(hist) or 1
    fg = sum(hist[128:])  # pixels brighter than mid -> garment
    frac = fg / total
    return _MASK_MIN_FRACTION <= frac <= _MASK_MAX_FRACTION


def build_cutout(
    *,
    original: Image.Image,
    box_2d: List[int],
    mask_b64: Optional[str] = None,
) -> Optional[Cutout]:
    """Build one garment cutout. Returns None if the box is unusable."""
    img = original.convert("RGB")
    box = _box_to_pixels(box_2d, img.width, img.height)
    if box is None:
        return None
    x0, y0, x1, y1 = box
    crop = img.crop((x0, y0, x1, y1))

    # Isolation: alpha-composite the masked garment onto a neutral background so
    # the stored cutout (used by BOTH the review deck and Wave-2 generation) is the
    # garment alone, not the full scene. Falls back to the rectangular box crop when
    # no reliable mask is available — logged so the mask hit-rate is observable.
    used_mask = False
    if not mask_b64:
        logger.info("cutout: mask MISS (absent) -> box crop")
    else:
        mask = _decode_mask(mask_b64, crop.size)
        if mask is None:
            logger.info("cutout: mask MISS (decode failed) -> box crop")
        elif not _mask_is_reliable(mask):
            logger.info("cutout: mask MISS (fg fraction outside %.2f-%.2f) -> box crop",
                        _MASK_MIN_FRACTION, _MASK_MAX_FRACTION)
        else:
            bg = Image.new("RGB", crop.size, _NEUTRAL_BG)
            bg.paste(crop, (0, 0), mask)  # mask as alpha
            crop = bg
            used_mask = True
            logger.info("cutout: mask HIT -> isolated garment on neutral bg")

    out = io.BytesIO()
    crop.save(out, format="JPEG", quality=90)
    return Cutout(data=out.getvalue(), suffix=".jpg",
                  content_type="image/jpeg", used_mask=used_mask)
