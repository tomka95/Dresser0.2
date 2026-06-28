"""Garment detection for photo ingestion (Wave 1).

A NEW, schema-first detector that is deliberately SEPARATE from
``AIProvider.detect_clothing_items_from_image`` (which feeds the Wave-2 generation
pipeline and parses free text with a regex). Touching that shared function would
change the contract behind /outfit-image, so the photo path gets its own entry point
with a real Pydantic ``response_schema`` — no regex, validated output.

Per garment the model returns:
  * box_2d  — REQUIRED, [ymin, xmin, ymax, xmax] normalized 0..1000 (Gemini's
              bounding-box convention). The cutout stage maps this onto the original
              pixels.
  * mask    — OPTIONAL base64 PNG probability map within the box, when the model
              emits it in the same call. The cutout stage uses it for a clean alpha
              cutout and falls back to the rectangular box crop when it is absent or
              unreliable. No external segmentation model is involved.
  * the usual attributes (category/color/pattern/material/fit/brand/name) + per-field
    confidence, so the swipe deck can flag weak fields exactly as the Gmail path does.

PERSON SCOPE (privacy): the model also reports ``person_count``. The caller HOLDS an
upload with >1 person rather than guessing which person is the user. A flat-lay /
no-person photo (person_count == 0) is treated as "every garment in frame is the
user's".
"""
from __future__ import annotations

import json
import logging
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger(__name__)


class GarmentCategory(str, Enum):
    """Closet category vocabulary — MUST match review_service._CATEGORY_ENUM so a
    staged candidate's category is valid both at confirm and for inline edits."""

    top = "top"
    bottom = "bottom"
    dress = "dress"
    outerwear = "outerwear"
    shoes = "shoes"
    accessories = "accessories"
    other = "other"


class GarmentFieldConfidence(BaseModel):
    """Per-field confidence [0,1]; mirrors the Gmail extractor's FieldConfidence so
    low_confidence_fields works identically in the deck."""

    name: Optional[float] = None
    category: Optional[float] = None
    color: Optional[float] = None
    pattern: Optional[float] = None
    material: Optional[float] = None
    fit: Optional[float] = None
    brand: Optional[float] = None


class GarmentRegion(BaseModel):
    """One detected garment with its image region + attributes."""

    name: str
    category: GarmentCategory = GarmentCategory.other
    color: Optional[str] = None
    pattern: Optional[str] = None
    material: Optional[str] = None
    fit: Optional[str] = None
    brand: Optional[str] = None
    # [ymin, xmin, ymax, xmax], normalized 0..1000 (Gemini convention). REQUIRED.
    box_2d: List[int] = Field(default_factory=list)
    # Base64 PNG probability mask within the box, if the model produced one.
    mask: Optional[str] = None
    confidence_overall: Optional[float] = None
    confidence: GarmentFieldConfidence = Field(default_factory=GarmentFieldConfidence)


class DetectionResult(BaseModel):
    """The full detection payload for one photo."""

    # Distinct PEOPLE visible. 0 = flat-lay/no person; >1 => caller holds the upload.
    person_count: int = 0
    garments: List[GarmentRegion] = Field(default_factory=list)


_SYSTEM_INSTRUCTION = (
    "You are a precise garment detector for a personal-closet app. You are given ONE "
    "photo. Identify the wearable CLOTHING garments in it and, for EACH, return a "
    "tight 2D bounding box and (if you can) a segmentation mask.\n"
    "\n"
    "RULES:\n"
    "- Include only wearable garments: tops, bottoms, dresses, outerwear, and "
    "shoes/footwear. Shoes ARE clothing.\n"
    "- EXCLUDE jewelry, watches, bags, hats, sunglasses, phones, props, furniture, "
    "and background objects. If unsure something is clothing, omit it.\n"
    "- box_2d MUST be [ymin, xmin, ymax, xmax], each an integer 0..1000 normalized to "
    "the image (0,0 = top-left). One box per garment, as tight as possible.\n"
    "- mask: if you can produce a segmentation mask for the garment, include it as a "
    "base64-encoded PNG string of the region; otherwise omit it.\n"
    "- category MUST be one of: top, bottom, dress, outerwear, shoes, accessories, "
    "other.\n"
    "- person_count = the number of DISTINCT PEOPLE visible (0 if it is a flat-lay or "
    "product shot with no person). Count people, not garments.\n"
    "- Give a per-field confidence in 0..1 and an overall confidence per garment.\n"
    "- Do not invent a brand you cannot read; leave it null."
)


def _coerce_result(raw) -> DetectionResult:
    """Turn the SDK response into a validated DetectionResult, defensively."""
    # google-genai populates `.parsed` with an instance of the response_schema when
    # parsing succeeds; fall back to the raw text otherwise.
    parsed = getattr(raw, "parsed", None)
    if isinstance(parsed, DetectionResult):
        return parsed
    if isinstance(parsed, dict):
        return DetectionResult.model_validate(parsed)

    text = getattr(raw, "text", None)
    if isinstance(text, str) and text.strip():
        try:
            return DetectionResult.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("photo detection: could not parse model output: %s", exc)
    return DetectionResult(person_count=0, garments=[])


def detect_garments_with_regions(
    *,
    image_bytes: bytes,
    content_type: str,
    max_items: int = 12,
    provider=None,
) -> DetectionResult:
    """Detect garments + regions in one photo via Gemini structured output.

    ``provider`` is injectable for tests; defaults to the shared AIProvider singleton.
    Never raises on a model/parse failure — returns an empty DetectionResult so the
    caller stages nothing rather than 500ing.
    """
    if provider is None:
        from app.services.ai_provider import get_ai_provider

        provider = get_ai_provider()

    user_text = (
        f"Detect up to {max_items} clothing garments in this photo. Return person_count "
        "and the garments array per the schema. Boxes are required; masks optional."
    )
    image_parts = [{"inline_data": {"mime_type": content_type, "data": image_bytes}}]

    try:
        resp = provider.generate_structured(
            model=settings.GEMINI_DETECT_MODEL,
            system_instruction=_SYSTEM_INSTRUCTION,
            user_text=user_text,
            response_schema=DetectionResult,
            image_parts=image_parts,
            temperature=0.0,
        )
    except Exception as exc:  # network / quota / SDK error -> stage nothing
        logger.warning("photo detection call failed: %s", exc)
        return DetectionResult(person_count=0, garments=[])

    result = _coerce_result(resp)
    # Defensive cap (the model is asked for <= max_items but trust nothing).
    if len(result.garments) > max_items:
        result.garments = result.garments[:max_items]
    return result
