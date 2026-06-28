"""Hardened validation + sanitization for USER-UPLOADED images (Wave 1 photo ingest).

The Gmail image path fetches remote bytes through image_guard (SSRF + magic-byte
sniff). The photo-ingest path takes bytes straight from the user's device, so it
needs its own front door with the same paranoia PLUS two things the email path never
worried about: decompression bombs and EXIF/GPS metadata.

Every uploaded image MUST pass through ``validate_and_sanitize`` before it is hashed,
stored, or sent to any model. The function:

  1. Caps raw size (cheap pre-decode guard).
  2. Sniffs the MAGIC BYTES — the declared Content-Type is never trusted.
  3. Decodes under a hard ``Image.MAX_IMAGE_PIXELS`` ceiling so a 100k x 100k
     "pixel flood" PNG raises DecompressionBombError instead of exhausting memory.
  4. Enforces an explicit per-side dimension ceiling.
  5. STRIPS ALL METADATA (EXIF incl. GPS, ICC, XMP) by re-encoding pixels only, then
     asserts the re-encoded bytes carry no EXIF. GPS never reaches storage.

It also derives the sha256 of the ORIGINAL bytes (idempotency key — re-uploading the
exact same file is caught) and a perceptual dHash (near-duplicate detection).

Decode is CPU-bound; callers in async contexts should offload to a thread.
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from typing import Optional

from PIL import Image

# Pillow ships its own decompression-bomb warning/error machinery; we make it a hard
# ceiling. 40 MP comfortably covers any phone camera (48 MP sensors bin to ~12 MP
# output) while refusing the absurd dimensions a bomb relies on.
MAX_IMAGE_PIXELS = 40_000_000
# Explicit per-side ceiling (a 39 MP 39000x1000 sliver would pass the pixel test but
# is still hostile). Phones top out well under this.
MAX_DIMENSION = 12_000
# Raw upload byte cap — mirrors the existing /outfit-image limit (main.py).
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# Formats we accept AND can losslessly re-encode with Pillow. HEIC/AVIF are NOT here:
# iOS Safari transcodes HEIC to JPEG on <input type=file> upload, and Pillow can't
# decode HEIC without an extra native plugin — see module note / status report.
_SNIFFERS = {
    "jpeg": lambda b: b[:3] == b"\xff\xd8\xff",
    "png": lambda b: b[:8] == b"\x89PNG\r\n\x1a\n",
    "webp": lambda b: len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP",
}
# Canonical format token -> (Pillow format, content-type, file suffix).
_ENCODE = {
    "jpeg": ("JPEG", "image/jpeg", ".jpg"),
    "png": ("PNG", "image/png", ".png"),
    "webp": ("WEBP", "image/webp", ".webp"),
}


class ImageValidationError(ValueError):
    """An uploaded image failed validation. The message is user-safe (no bytes/paths).

    The route maps this to HTTP 400/413. Messages name only the failed check, never
    image content.
    """


@dataclass(frozen=True)
class SanitizedImage:
    """The result of validating + sanitizing one uploaded image."""

    data: bytes          # EXIF-stripped, re-encoded bytes — what gets stored/sent
    fmt: str             # canonical token: 'jpeg' | 'png' | 'webp'
    content_type: str    # e.g. 'image/jpeg'
    suffix: str          # e.g. '.jpg'
    width: int
    height: int
    sha256: str          # sha256 of the ORIGINAL upload bytes (idempotency key)
    phash: str           # 16-hex-char 64-bit perceptual dHash (near-dup detection)


def sniff_image_format(data: bytes) -> Optional[str]:
    """Return the canonical format token from the MAGIC BYTES, or None.

    The declared Content-Type is irrelevant here — only the actual leading bytes
    decide. A mismatch between a spoofed Content-Type and the real bytes is exactly
    what this defeats.
    """
    for token, test in _SNIFFERS.items():
        try:
            if test(data):
                return token
        except (IndexError, TypeError):
            continue
    return None


def _dhash(image: Image.Image) -> str:
    """64-bit difference hash (8x8) as 16 lowercase hex chars.

    Resizes to 9x8 greyscale and compares horizontally-adjacent pixels. Robust to
    re-compression / minor crops, so two near-identical phone shots collide.
    """
    small = image.convert("L").resize((9, 8), Image.BILINEAR)
    px = list(small.getdata())
    bits = 0
    for row in range(8):
        base = row * 9
        for col in range(8):
            bits = (bits << 1) | (1 if px[base + col] > px[base + col + 1] else 0)
    return f"{bits:016x}"


def phash_distance(a: str, b: str) -> int:
    """Hamming distance between two dHash hex strings (0..64). Lower = more similar."""
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def validate_and_sanitize(data: bytes) -> SanitizedImage:
    """Validate, decode-guard, and STRIP METADATA from one uploaded image.

    Raises ImageValidationError on any failure. On success returns a SanitizedImage
    whose ``data`` is safe to store and forward (no EXIF/GPS).
    """
    if not data:
        raise ImageValidationError("empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageValidationError(
            f"file exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit"
        )

    fmt = sniff_image_format(data)
    if fmt is None:
        raise ImageValidationError("unrecognized image format (expected JPEG, PNG, or WebP)")

    sha = hashlib.sha256(data).hexdigest()

    # Hard decompression-bomb ceiling for THIS decode. Set on the module class; restore
    # so we never leak a relaxed/strict global to other Pillow users.
    prev_max = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        try:
            img = Image.open(io.BytesIO(data))
            img.load()  # force full decode here so a bomb/truncation raises now
        except Image.DecompressionBombError:
            raise ImageValidationError("image dimensions too large")
        except ImageValidationError:
            raise
        except Exception:
            # Corrupt / truncated / not actually decodable despite a valid magic header.
            raise ImageValidationError("could not decode image")

        width, height = img.size
        if width <= 0 or height <= 0:
            raise ImageValidationError("could not decode image")
        if width > MAX_DIMENSION or height > MAX_DIMENSION:
            raise ImageValidationError(
                f"image side exceeds {MAX_DIMENSION}px limit"
            )

        phash = _dhash(img)

        pil_fmt, content_type, suffix = _ENCODE[fmt]

        # --- METADATA STRIP --------------------------------------------------
        # Re-encode pixels into a FRESH image. Pillow only writes EXIF/ICC when you
        # explicitly pass them, so a plain save() drops all of it; building a new
        # Image from the pixel buffer guarantees no info dict (XMP/GPS) tags along.
        save_mode = img.mode
        if pil_fmt == "JPEG" and save_mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
            save_mode = "RGB"
        clean = Image.new(save_mode, img.size)
        clean.putdata(list(img.getdata()))

        out = io.BytesIO()
        save_kwargs = {"format": pil_fmt}
        if pil_fmt == "JPEG":
            save_kwargs["quality"] = 90
        clean.save(out, **save_kwargs)
        sanitized = out.getvalue()
    finally:
        Image.MAX_IMAGE_PIXELS = prev_max

    # Verify the strip actually worked — no EXIF must survive into stored bytes.
    check = Image.open(io.BytesIO(sanitized))
    exif = check.getexif()
    if exif and len(exif):
        # Should be unreachable (we rebuilt from pixels); fail closed if a Pillow
        # version ever round-trips metadata so GPS can never leak silently.
        raise ImageValidationError("failed to strip image metadata")

    return SanitizedImage(
        data=sanitized,
        fmt=fmt,
        content_type=content_type,
        suffix=suffix,
        width=width,
        height=height,
        sha256=sha,
        phash=phash,
    )
