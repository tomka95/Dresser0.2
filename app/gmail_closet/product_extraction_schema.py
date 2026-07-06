"""Typed schema + sanitizers for the product-page extractor (Wave F1b).

Fork of extraction_schema (receipts) for "one product from a fetched product page".
The Pydantic model is handed straight to Gemini as `response_schema` (structured
output), so the model is FORCED to return valid typed JSON; we re-validate with the
same model and NEVER regex the output.

Shares the language-agnostic ClosetCategory enum and normalize_currency helper with
the receipt path. Adds the FULL universal garment schema (subcategory / colors /
pattern / material / fit / formality / warmth / seasons / occasions) plus
brand / merchant / price / currency + per-field confidence.

SECURITY: extracted strings come from an untrusted web page. `sanitize_text` flattens
+ truncates every string before it is stored or fed into any downstream prompt (the
embedding canonical text, the stylist's shop-results context), neutralizing the common
multi-line prompt-injection vector by collapsing newlines and capping length.
"""
from __future__ import annotations

import re
import unicodedata
from typing import List, Optional

from pydantic import BaseModel, Field

# Reuse the closet enum + currency normalizer from the receipt schema — one source.
from .extraction_schema import ClosetCategory, normalize_currency  # noqa: F401


# ---------------------------------------------------------------------------
# Structured-output models (the shape Gemini is forced to return for ONE product).
# ---------------------------------------------------------------------------

class ProductFieldConfidence(BaseModel):
    """Per-field 0..1 confidence for the extracted product."""
    name: Optional[float] = None
    brand: Optional[float] = None
    category: Optional[float] = None
    subcategory: Optional[float] = None
    color_primary: Optional[float] = None
    pattern: Optional[float] = None
    material: Optional[float] = None
    fit_silhouette: Optional[float] = None
    formality: Optional[float] = None
    warmth: Optional[float] = None
    price: Optional[float] = None


class ProductExtraction(BaseModel):
    """One product extracted from a product-page HTML.

    `is_clothing` is THE gate: when false, the ingest layer writes NOTHING to the
    products catalog (non-garment pages — electronics, gift cards, etc.).
    """
    is_clothing: bool = Field(description="THE gate: true only if this page sells a wearable garment/footwear/accessory.")
    name: str = Field(description="Product name, verbatim in the page's language (do not translate).")
    brand: Optional[str] = Field(default=None, description="Brand, if determinable (often embedded in the name).")
    merchant: Optional[str] = Field(default=None, description="Selling merchant / store name.")
    category: ClosetCategory = Field(description="Closest of the fixed closet categories.")
    subcategory: Optional[str] = Field(default=None, description="Free-text garment subtype, e.g. 'denim jacket', 'midi dress'.")
    color_primary: Optional[str] = Field(default=None, description="Dominant color name.")
    color_primary_hex: Optional[str] = Field(default=None, description="Dominant color as #RRGGBB if inferable, else null.")
    color_secondary: Optional[str] = Field(default=None, description="Secondary color name, if any.")
    pattern: Optional[str] = Field(default=None, description="e.g. solid, striped, floral, plaid, graphic.")
    material: Optional[str] = Field(default=None, description="Dominant material, e.g. cotton, denim, wool, leather.")
    fit_silhouette: Optional[str] = Field(default=None, description="e.g. slim, relaxed, oversized, straight, a-line.")
    formality: Optional[int] = Field(default=None, description="1=very casual .. 5=black-tie formal.")
    warmth: Optional[int] = Field(default=None, description="1=lightweight/hot .. 3=heavy/cold.")
    seasons: List[str] = Field(default_factory=list, description="Seasons it suits (spring/summer/fall/winter); empty = year-round/unknown.")
    occasions: List[str] = Field(default_factory=list, description="e.g. casual, work, formal, evening, athletic, outdoor.")
    price: Optional[float] = Field(default=None, description="Current selling price as a number only (no symbol). Sale price if shown.")
    currency: Optional[str] = Field(default=None, description="3-letter ISO currency code (USD, ILS, EUR, ...).")
    in_stock: Optional[bool] = Field(default=None, description="True if purchasable/in stock, false if sold out, null if unknown.")
    canonical_url: Optional[str] = Field(default=None, description="The page's own canonical/og:url product link, if present.")
    confidence: ProductFieldConfidence = Field(default_factory=ProductFieldConfidence)
    overall_confidence: float = Field(default=0.0, description="Overall 0..1 confidence in this extraction.")


# ---------------------------------------------------------------------------
# Sanitizers (no LLM) applied before store / any downstream prompt.
# ---------------------------------------------------------------------------

# Field length caps: names get a generous budget, attribute strings a tight one.
NAME_MAX_LEN = 200
ATTR_MAX_LEN = 80
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")          # C0/C1 control chars
# Zero-width + bidi controls (injection-cloaking): ZWSP..RLM, LRE..RLO, WJ, BOM.
_ZERO_WIDTH_RE = re.compile("[​-‏‪-‮⁠﻿]")
_WS_RE = re.compile(r"\s+")


def sanitize_text(value: Optional[str], *, max_len: int = ATTR_MAX_LEN) -> Optional[str]:
    """Flatten + truncate an untrusted product string. None-safe.

    Removes control + zero-width/bidi chars, collapses ALL whitespace (incl. newlines)
    to single spaces, NFC-normalizes, strips, and caps length. Collapsing newlines is
    the point: it neutralizes the multi-line "ignore previous instructions" injection
    block by turning it into one short inert line, and keeps stored attributes tidy.
    Returns None for empty/whitespace-only input.
    """
    if value is None:
        return None
    s = unicodedata.normalize("NFC", str(value))
    s = _ZERO_WIDTH_RE.sub("", s)
    s = _CONTROL_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    if not s:
        return None
    return s[:max_len]


def sanitize_hex(value: Optional[str]) -> Optional[str]:
    """Accept only a well-formed #RRGGBB, else None (never store arbitrary text here)."""
    if not value:
        return None
    s = str(value).strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", s):
        return s.lower()
    return None


def clamp_int(value: Optional[int], lo: int, hi: int) -> Optional[int]:
    """Clamp a model-returned int into [lo, hi]; None on missing/unparseable."""
    if value is None:
        return None
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return None


def sanitize_str_list(values: Optional[List[str]], *, max_items: int = 8) -> List[str]:
    """Sanitize a list of short attribute strings (seasons/occasions/geo), dropping
    empties and capping count. Lowercased for stable downstream matching."""
    out: List[str] = []
    for v in (values or []):
        clean = sanitize_text(v, max_len=ATTR_MAX_LEN)
        if clean:
            out.append(clean.lower())
        if len(out) >= max_items:
            break
    return out
