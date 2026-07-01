"""Wave 1 upload-security tests: magic-byte sniff, size/dimension/bomb guards, and
the EXIF/GPS strip on user-uploaded photos."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from app.utils import image_validation as iv
from app.utils.image_validation import (
    ImageValidationError,
    phash_distance,
    sniff_image_format,
    validate_and_sanitize,
)


def _jpeg(color=(120, 30, 30), size=(64, 64), exif: Image.Exif | None = None) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    if exif is not None:
        img.save(buf, "JPEG", exif=exif)
    else:
        img.save(buf, "JPEG")
    return buf.getvalue()


def _png(color=(30, 120, 30), size=(64, 64)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# --- magic-byte sniffing (Content-Type is never trusted) --------------------

def test_sniff_detects_real_formats():
    assert sniff_image_format(_jpeg()) == "jpeg"
    assert sniff_image_format(_png()) == "png"


def test_sniff_rejects_non_image_bytes():
    assert sniff_image_format(b"<html>not an image</html>") is None
    assert sniff_image_format(b"") is None


def test_spoofed_content_type_is_irrelevant():
    # A text payload a client might mislabel "image/jpeg" has no JPEG magic -> rejected.
    with pytest.raises(ImageValidationError):
        validate_and_sanitize(b"GIF89a-ish but actually junk")


# --- size / dimension / decompression-bomb guards ---------------------------

def test_oversize_raw_rejected(monkeypatch):
    monkeypatch.setattr(iv, "MAX_UPLOAD_BYTES", 1000)
    with pytest.raises(ImageValidationError):
        validate_and_sanitize(_jpeg(size=(256, 256)))


def test_dimension_ceiling_rejected(monkeypatch):
    monkeypatch.setattr(iv, "MAX_DIMENSION", 100)
    with pytest.raises(ImageValidationError):
        validate_and_sanitize(_png(size=(64, 200)))  # 200px side > 100 ceiling


def test_decompression_bomb_rejected(monkeypatch):
    # Force the pixel ceiling below the test image so Pillow raises DecompressionBomb.
    monkeypatch.setattr(iv, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(ImageValidationError):
        validate_and_sanitize(_png(size=(64, 64)))  # 4096px > 2*100 -> bomb error


def test_empty_rejected():
    with pytest.raises(ImageValidationError):
        validate_and_sanitize(b"")


# --- EXIF / GPS metadata strip ----------------------------------------------

def test_exif_is_stripped():
    exif = Image.Exif()
    exif[0x010F] = "TestCamMake"  # Make tag
    exif[0x0110] = "TestModel"    # Model tag
    raw = _jpeg(exif=exif)
    # Sanity: the original really does carry EXIF.
    assert len(Image.open(io.BytesIO(raw)).getexif()) > 0

    out = validate_and_sanitize(raw)
    assert len(Image.open(io.BytesIO(out.data)).getexif()) == 0


def test_gps_exif_is_stripped():
    exif = Image.Exif()
    # GPS IFD (0x8825) — the privacy-critical one. Ref strings (N/W) embed cleanly.
    exif[0x8825] = {1: "N", 3: "W"}
    raw = _jpeg(exif=exif)
    assert Image.open(io.BytesIO(raw)).getexif().get_ifd(0x8825)  # GPS really present
    out = validate_and_sanitize(raw)
    reopened = Image.open(io.BytesIO(out.data))
    assert len(reopened.getexif()) == 0
    # No GPS IFD survives.
    assert not reopened.getexif().get_ifd(0x8825)


# --- happy path + derived fields --------------------------------------------

def test_sanitized_fields_and_idempotency_hash():
    raw = _jpeg()
    out = validate_and_sanitize(raw)
    assert out.fmt == "jpeg"
    assert out.content_type == "image/jpeg"
    assert out.suffix == ".jpg"
    assert out.width == 64 and out.height == 64
    assert len(out.sha256) == 64
    assert len(out.phash) == 16  # 64-bit dHash as hex
    # sha256 is over the ORIGINAL bytes -> re-uploading the same file recomputes equal.
    assert validate_and_sanitize(raw).sha256 == out.sha256


def test_phash_distance_near_duplicate():
    # dHash compares horizontally-adjacent pixels and sets a bit only on a left>right
    # DROP, so the image needs both rising and falling edges along x. Alternating
    # vertical bands give a rich, non-zero hash.
    base = Image.new("RGB", (128, 128))
    for x in range(128):
        v = 255 if (x // 8) % 2 == 0 else 0
        for y in range(128):
            base.putpixel((x, y), (v, v, v))
    b = io.BytesIO(); base.save(b, "PNG")
    # Re-encode the SAME image as JPEG (lossy) -> near-identical perceptual hash.
    jb = io.BytesIO(); base.convert("RGB").save(jb, "JPEG", quality=85)

    h1 = validate_and_sanitize(b.getvalue()).phash
    h2 = validate_and_sanitize(jb.getvalue()).phash
    assert phash_distance(h1, h2) <= 4  # very close

    # A clearly different image (solid) is far away.
    solid = io.BytesIO(); Image.new("RGB", (128, 128), (200, 50, 50)).save(solid, "PNG")
    h3 = validate_and_sanitize(solid.getvalue()).phash
    assert phash_distance(h1, h3) >= 8
