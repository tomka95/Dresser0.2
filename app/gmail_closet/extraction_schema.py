"""Typed schema + normalizers for the phase-3c receipt extractor.

The Pydantic models here are passed straight to Gemini as `response_schema`
(structured output): the SDK derives an OpenAPI schema from the type hints, so
the model is FORCED to return valid, typed JSON in this exact shape. We then
re-validate the JSON with the same models — we never regex the model output.

`category` is constrained to ClosetCategory, the language-agnostic closet enum
that mirrors packages/contracts/src/closet.ts. A Hebrew or English product name
keeps its source-language text; only the category collapses to this enum.

Also holds the small deterministic helpers the staging layer needs:
  * normalize_currency  -> 3-char ISO or None (honours the DB length(currency)=3 guard)
  * normalize_order_date -> datetime.date or None
  * make_content_key    -> hash(normalized_name + size + color + unit_price), the
                           per-user staging dedup key (collapses the same owned item
                           across the order/shipping-confirmation email pair)
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Closet category enum — mirrors packages/contracts/src/closet.ts exactly.
# Language-agnostic: a Hebrew receipt's "חולצה" still maps to `top`.
# ---------------------------------------------------------------------------

class ClosetCategory(str, Enum):
    top = "top"
    bottom = "bottom"
    dress = "dress"
    outerwear = "outerwear"
    shoes = "shoes"
    accessories = "accessories"
    other = "other"


# ---------------------------------------------------------------------------
# Structured-output models (the shape Gemini is forced to return).
# Optional fields become `nullable` in the derived schema; required fields
# (name, category, is_purchase, is_clothing, overall_confidence) are always set.
# ---------------------------------------------------------------------------

class FieldConfidence(BaseModel):
    """Per-field 0..1 confidence for one extracted item."""
    name: Optional[float] = None
    brand: Optional[float] = None
    category: Optional[float] = None
    color: Optional[float] = None
    size: Optional[float] = None
    unit_price: Optional[float] = None


class ExtractedItem(BaseModel):
    """One line item on a receipt. Product name is kept in its SOURCE language."""
    name: str = Field(description="Product name, verbatim in the email's language (do not translate).")
    brand: Optional[str] = None
    category: ClosetCategory = Field(description="One of the fixed closet categories.")
    color: Optional[str] = None
    size: Optional[str] = None
    qty: int = Field(default=1, description="Quantity ordered for this line.")
    unit_price: Optional[float] = Field(default=None, description="Price per single unit, numeric only.")
    is_return: bool = Field(default=False, description="True if this line is a return/refund/credit.")
    image_ref: Optional[str] = Field(
        default=None,
        description="Reference to an inline image part for this item, if one is clearly identifiable; else null.",
    )
    confidence: FieldConfidence = Field(default_factory=FieldConfidence)


class ExtractedReceipt(BaseModel):
    """Top-level extraction result for a single email.

    `is_clothing` is THE gate: when false (or when there are no clothing items),
    the staging layer writes NOTHING to ingest_candidates.
    """
    is_purchase: bool = Field(description="True if this email is a purchase/order/receipt at all.")
    is_clothing: bool = Field(description="THE gate: true only if this purchase contains wearable clothing/footwear.")
    merchant: Optional[str] = None
    order_id: Optional[str] = None
    order_date: Optional[str] = Field(default=None, description="Order date as YYYY-MM-DD if present, else null.")
    currency: Optional[str] = Field(default=None, description="3-letter ISO currency code (e.g. USD, ILS, EUR).")
    items: List[ExtractedItem] = Field(default_factory=list)
    overall_confidence: float = Field(
        default=0.0, description="Overall 0..1 confidence in this extraction."
    )


# ---------------------------------------------------------------------------
# Deterministic normalizers (no LLM) used at staging time.
# ---------------------------------------------------------------------------

# Symbol -> ISO. '$' is ambiguous (USD/CAD/AUD); default to USD for v1.
_CURRENCY_SYMBOLS = {
    "$": "USD",
    "₪": "ILS",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "₹": "INR",
}
# Hebrew abbreviations / words for shekel that the model may echo back.
_CURRENCY_WORDS = {
    'ש"ח': "ILS",
    "שח": "ILS",
    "שקל": "ILS",
    "שקלים": "ILS",
    "NIS": "ILS",
}


def normalize_currency(raw: Optional[str]) -> Optional[str]:
    """Coerce a model-returned currency to a 3-char ISO code, else None.

    Returning None for anything we can't confidently map keeps the DB
    `length(currency) = 3` CHECK constraint satisfied (NULL is allowed).
    """
    if not raw:
        return None
    s = raw.strip()
    upper = s.upper()
    # Explicit words/abbreviations first, so "NIS"/"שקל" map to ILS rather than
    # being passed through verbatim (a 3-letter Hebrew word is len 3 + isalpha too).
    for word, code in _CURRENCY_WORDS.items():
        if word.upper() in upper or word in s:
            return code
    for sym, code in _CURRENCY_SYMBOLS.items():
        if sym in s:
            return code
    # Bare 3-letter ASCII ISO code (USD, EUR, ...). isascii() excludes Hebrew.
    if len(upper) == 3 and upper.isascii() and upper.isalpha():
        return upper
    return None


def normalize_order_date(raw: Optional[str]) -> Optional[date]:
    """Parse a YYYY-MM-DD prefix to a date; None on anything unparseable."""
    if not raw:
        return None
    s = raw.strip()[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def normalize_name(name: Optional[str]) -> str:
    """Lowercase + collapse whitespace — the stable form used in the dedup key."""
    return " ".join((name or "").lower().split())


def _price_key(unit_price: Optional[float]) -> str:
    """Stable 2-dp string for the dedup key; empty when price is unknown."""
    if unit_price is None:
        return ""
    try:
        return f"{float(unit_price):.2f}"
    except (TypeError, ValueError):
        return ""


def make_content_key(
    name: Optional[str],
    size: Optional[str],
    color: Optional[str],
    unit_price: Optional[float],
) -> str:
    """CONTENT dedup key = hash(normalized_name + size + color + unit_price).

    Deliberately message-INDEPENDENT: the same owned item appearing in both the
    order-confirmation and shipping-confirmation emails produces the SAME key, so
    staging collapses them to one candidate via UNIQUE(user_id, source_line_key).
    Truncated sha256 hex (matches the content_hash convention in fetch_service).
    Per-user scoping comes from the UNIQUE being on (user_id, source_line_key); the
    key itself stays user-agnostic. Two genuinely identical purchases collapse to
    one card (acceptable for v1; seen_count records how many emails contributed).
    """
    parts = [
        normalize_name(name),
        (size or "").strip().lower(),
        (color or "").strip().lower(),
        _price_key(unit_price),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
