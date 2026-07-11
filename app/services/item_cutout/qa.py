"""QA gate for item-cutout mattes (Collage Phase 1) — pure PIL/numpy/scipy, no
model, no DB, no storage.

A matte that fails here is marked ``no_matte`` and the item renders FLAT on its
own tile in the collage — the failure mode is "less pretty", never "patchy
rectangle" and never a mangled garment. The gate encodes what the Phase-0 spike
showed can actually go wrong with a salience model on this closet:

  * the model mattes a SUB-OBJECT instead of the garment (isnet kept only the
    flower graphic of a white tee) -> the KEY CROSS-CHECK below catches it by
    comparing the matte's area against a cheap border-flood content estimate
    (the same estimate the legacy collage key used — it over-includes shadows,
    so the matte only has to reach a conservative fraction of it);
  * the matte disintegrates into speckle (white leather went see-through under
    the classical key) -> the DOMINANT-BLOB check requires one connected region
    to carry most of the opaque area;
  * the matte runs off the frame edge (didn't find a bounded object — the
    generation invariant demands a margin on every side, so real cards never
    legitimately touch the border) -> the BORDER-CONTACT check;
  * degenerate everything/nothing mattes -> the AREA-FRACTION bounds.

All checks run on a <=320px thumbnail: the verdict is about structure, not
pixels, and this keeps the gate ~free next to the ~100ms model call.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageOps

# Opaque = alpha above this (the model emits soft edges; mid-grey alpha at the
# rim is expected and shouldn't count as "body" for structural checks).
_OPAQUE_THRESHOLD = 127

# Degenerate-area bounds: a matte keeping <2% of the frame found no garment; one
# keeping >97% found no background. Both are refusals, not cutouts.
_MIN_AREA_FRAC = 0.02
_MAX_AREA_FRAC = 0.97

# One connected region must carry at least this share of the opaque area —
# below it the "cutout" is confetti, not a garment.
_MIN_DOMINANT_FRAC = 0.75

# At most this fraction of border pixels may be opaque. Real cards have a
# catalog margin (invariant rule 3); a matte hugging the frame edge means the
# model never isolated a bounded object.
_MAX_BORDER_FRAC = 0.02

# Key cross-check: the matte must cover at least this fraction of the
# border-flood content estimate, when that estimate is available. The flood
# estimate INCLUDES baked shadows and halo (it over-counts garment), so the bar
# is deliberately low — u2net's clean mattes land ~0.6-1.0; the flower-only
# failure lands ~0.1.
_MIN_KEY_COVER_RATIO = 0.35
# The flood estimate is only trusted when it actually flooded a product-shot
# background (same posture as the legacy collage key's _MIN_BG_FRACTION).
_MIN_KEY_BG_FRAC = 0.30
_KEY_TOLERANCE = 26

_THUMB = 320


@dataclass(frozen=True)
class QAVerdict:
    ok: bool
    reason: str  # 'ok' | the first failed check, for id+reason logging


def _thumb(img: Image.Image) -> Image.Image:
    t = img.copy()
    t.thumbnail((_THUMB, _THUMB))
    return t


def _key_content_frac(rgb: Image.Image) -> float:
    """Fraction of the frame the legacy border-flood key would call CONTENT, or
    0.0 when the border isn't a clean product-shot background (busy/gradient —
    the key has no opinion there, and the cross-check is skipped)."""
    a = np.asarray(rgb, dtype=np.int16)
    edge = np.concatenate([a[0, :, :], a[-1, :, :], a[:, 0, :], a[:, -1, :]])
    bg = np.median(edge, axis=0)
    near = (np.abs(a - bg).max(axis=2) <= _KEY_TOLERANCE)

    m = Image.fromarray(np.where(near, 255, 0).astype(np.uint8))
    framed = ImageOps.expand(m, border=1, fill=255)
    ImageDraw.floodfill(framed, (0, 0), 128, thresh=0)
    flooded = np.asarray(framed.crop((1, 1, 1 + m.width, 1 + m.height)))
    bg_frac = float((flooded == 128).mean())
    if bg_frac < _MIN_KEY_BG_FRAC:
        return 0.0
    return 1.0 - bg_frac


def qa_matte(rgba: Image.Image) -> QAVerdict:
    """Structural verdict on one RGBA matte. Never raises; any internal surprise
    is a refusal (fail-closed — a bad matte must not reach the collage)."""
    try:
        thumb = _thumb(rgba.convert("RGBA"))
        alpha = np.asarray(thumb.getchannel("A"))
        opaque = alpha > _OPAQUE_THRESHOLD
        total = opaque.size
        area = int(opaque.sum())

        frac = area / total
        if frac < _MIN_AREA_FRAC:
            return QAVerdict(False, "empty_matte")
        if frac > _MAX_AREA_FRAC:
            return QAVerdict(False, "full_frame_matte")

        # Border contact: share of frame-border pixels that are opaque.
        border = np.concatenate([opaque[0, :], opaque[-1, :], opaque[:, 0], opaque[:, -1]])
        if float(border.mean()) > _MAX_BORDER_FRAC:
            return QAVerdict(False, "border_contact")

        # Dominant connected blob (8-connectivity: thin straps stay one region).
        from scipy import ndimage  # arrives with rembg; local import keeps qa importable early

        labels, n = ndimage.label(opaque, structure=np.ones((3, 3), dtype=int))
        if n < 1:
            return QAVerdict(False, "empty_matte")
        largest = int(np.bincount(labels.ravel())[1:].max())
        if largest / area < _MIN_DOMINANT_FRAC:
            return QAVerdict(False, "fragmented_matte")

        # Cross-check against the cheap key estimate (catches sub-object mattes).
        key_frac = _key_content_frac(thumb.convert("RGB"))
        if key_frac > 0.0 and frac < _MIN_KEY_COVER_RATIO * key_frac:
            return QAVerdict(False, "undersized_vs_key")

        return QAVerdict(True, "ok")
    except Exception:
        return QAVerdict(False, "qa_error")
