"""Tier-1 deterministic receipt filter — multilingual, no LLM.

Architecture: LOCALE PACKS
Each language is a LocalePack with its own keyword sets. Adding a new locale =
adding a new LocalePack to _LOCALE_PACKS. No changes to filter logic required.

Current packs: English (en), Hebrew (he).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

from .retailers import is_known_retailer

# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------
# Hebrew has no case, but uses distinct final-letter forms (ם ן ץ ף ך) that
# differ from their mid-word equivalents. Normalizing them lets a phrase like
# "תשלום" match whether the word appears mid-sentence or at end-of-phrase.
# Latin text is unaffected — none of these code points overlap.
_HE_FINAL = str.maketrans("םןץףך", "מנצפכ")


def _normalize(text: str) -> str:
    """Lowercase + collapse Hebrew final-letter forms for consistent substring matching."""
    return text.lower().translate(_HE_FINAL)


def _norm_phrases(phrases: Tuple[str, ...]) -> Tuple[str, ...]:
    return tuple(_normalize(p) for p in phrases)


# ---------------------------------------------------------------------------
# Locale pack
# ---------------------------------------------------------------------------

@dataclass
class LocalePack:
    """Keyword signals for one language/locale.

    All phrase tuples are pre-normalized at construction time so per-message
    matching is a plain 'phrase in normalized_text' check with no extra work.
    """
    name: str
    receipt_phrases: Tuple[str, ...]
    shipping_phrases: Tuple[str, ...]
    marketing_phrases: Tuple[str, ...]
    newsletter_phrases: Tuple[str, ...]

    def __post_init__(self) -> None:
        self.receipt_phrases   = _norm_phrases(self.receipt_phrases)
        self.shipping_phrases  = _norm_phrases(self.shipping_phrases)
        self.marketing_phrases = _norm_phrases(self.marketing_phrases)
        self.newsletter_phrases = _norm_phrases(self.newsletter_phrases)


# ---------------------------------------------------------------------------
# English locale pack
# ---------------------------------------------------------------------------

_EN = LocalePack(
    name="en",
    receipt_phrases=(
        "order confirmation",
        "your order",
        "order #",
        "order number",
        "order id",
        "receipt",
        "invoice",
        "payment received",
        "payment confirmed",
        "thank you for your order",
        "thank you for your purchase",
        "items ordered",
        "items purchased",
        "you ordered",
        "billing summary",
        "payment summary",
        "order summary",
        "your purchase",
        "purchase confirmation",
        "total charged",
        "amount charged",
        "amount billed",
        "return confirmation",
        "return label",
    ),
    shipping_phrases=(
        "out for delivery",
        "has been delivered",
        "package delivered",
        "delivery attempted",
        "delivery notice",
        "parcel delivered",
        "your package has arrived",
    ),
    marketing_phrases=(
        "unsubscribe",
        "opt out",
        "opt-out",
        "email preferences",
        "manage preferences",
        "manage your subscription",
        "view this email in your browser",
        "view in browser",
    ),
    newsletter_phrases=(
        "shop now",
        "shop the collection",
        "new arrivals",
        "new collection",
        "limited time offer",
        "flash sale",
        "sale ends",
        "our latest",
        "check out our",
        "exclusive offer",
        "% off everything",
    ),
)

# ---------------------------------------------------------------------------
# Hebrew locale pack
# ---------------------------------------------------------------------------

_HE = LocalePack(
    name="he",
    receipt_phrases=(
        # Core receipt/invoice terms
        "חשבונית",          # invoice (also covers חשבונית מס — tax invoice)
        "קבלה",             # receipt
        "מספר קבלה",        # receipt number
        # Order terms
        "הזמנה",            # order (covers אישור הזמנה, סיכום הזמנה, מספר הזמנה)
        "הזמנתך",           # your order (not a substring of הזמנה)
        "אישור הזמנה",      # order confirmation
        "סיכום הזמנה",      # order summary
        "מספר הזמנה",       # order number
        # Purchase terms
        "רכישה",            # purchase
        "רכישתך",           # your purchase
        "ביצעת רכישה",      # you made a purchase
        # Transaction / payment
        "עסקה",             # transaction
        "תשלום",            # payment (covers אישור תשלום, סה"כ לתשלום)
        # Thank-you lines
        "תודה על הזמנתך",   # thank you for your order
        "תודה על רכישתך",   # thank you for your purchase
    ),
    shipping_phrases=(
        # Pure shipping-notification signals (only cause a drop when no receipt/price signal)
        "נמסרה החבילה",     # the package was delivered (specific form, avoids נמסר substring risk)
        "יצא למסירה",       # out for delivery
        "החבילה הגיעה",     # the package arrived
        "המשלוח נמסר",      # the shipment was delivered
    ),
    marketing_phrases=(
        "להסרה מרשימת תפוצה",   # remove from mailing list
        "לחץ כאן להסרה",        # click here to remove (m.)
        "לחצי כאן להסרה",       # click here to remove (f.)
        "ביטול מנוי",           # cancel subscription
        "הסר מרשימה",           # remove from list
        "לביטול מנוי",          # to unsubscribe
        "ניהול העדפות",         # manage preferences
    ),
    newsletter_phrases=(
        "מוצרים חדשים",     # new products
        "קולקציה חדשה",     # new collection
        "מבצע מוגבל",       # limited offer
        "הנחה מיוחדת",      # special discount
    ),
)

# ---------------------------------------------------------------------------
# All active locale packs — extend here to add new languages
# ---------------------------------------------------------------------------

_LOCALE_PACKS: List[LocalePack] = [_EN, _HE]

# ---------------------------------------------------------------------------
# Price / currency regex — unified across all active locales
# ---------------------------------------------------------------------------
# EN: $ € £ ¥ ₹ ₪ + ISO codes USD EUR GBP CAD AUD JPY CHF INR MXN BRL ILS
# HE: ₪ (symbol, already in first alt) + ILS + ש"ח (abbreviation) + שקל (word)

_PRICE_RE = re.compile(
    # Currency symbol before number: $29.99  €1,299  ₪299
    r"(?:[\$€£¥₹₪]\s*\d[\d,]*(?:\.\d{1,2})?"
    # ISO code before number: USD 49.00  ILS 120
    r"|\b(?:USD|EUR|GBP|CAD|AUD|JPY|CHF|INR|MXN|BRL|ILS)\s*\d[\d,]*(?:\.\d{1,2})?"
    # Number before ISO code: 49.00 USD  120 ILS
    r"|\b\d[\d,]*(?:\.\d{1,2})?\s*(?:USD|EUR|GBP|CAD|AUD|JPY|CHF|INR|MXN|BRL|ILS)\b"
    # Hebrew abbreviation: 50 ש"ח  (sheqalim, very common in Israeli invoices)
    r'|[\d,]+(?:\.\d{1,2})?\s*ש"ח'
    # Hebrew word: 50 שקל  (requires leading digit to avoid false positives)
    r"|\b\d[\d,]*(?:\.\d{1,2})?\s*שקל\b)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public filter
# ---------------------------------------------------------------------------

def passes_tier1_filter(sender: str, subject: str, body: str) -> Tuple[bool, str]:
    """Return (keep: bool, reason: str) — deterministic, no LLM, multilingual.

    Positive signals → keep (unless a negative override applies):
      - is_known_retailer(sender)
      - price/currency pattern in subject or body
      - any locale pack's receipt phrase found in subject or body

    Negative overrides (only fire when NO positive receipt signal exists):
      - shipping_only: shipping phrase present, no price, no receipt keywords
      - marketing_newsletter: marketing or newsletter phrase present, no price, no receipt

    To add a new language: define a LocalePack and append to _LOCALE_PACKS above.
    """
    combined_raw = subject + " " + body
    combined = _normalize(combined_raw)

    has_price = bool(_PRICE_RE.search(combined_raw))
    is_retailer = is_known_retailer(sender)

    has_receipt = any(
        phrase in combined
        for pack in _LOCALE_PACKS
        for phrase in pack.receipt_phrases
    )

    # --- Negative: shipping-only ---------------------------------------------
    is_shipping_only = (
        any(
            phrase in combined
            for pack in _LOCALE_PACKS
            for phrase in pack.shipping_phrases
        )
        and not has_price
        and not has_receipt
    )
    if is_shipping_only:
        return False, "shipping_only"

    # --- Negative: pure marketing / newsletter -------------------------------
    has_marketing = any(
        phrase in combined
        for pack in _LOCALE_PACKS
        for phrase in pack.marketing_phrases
    )
    has_newsletter = any(
        phrase in combined
        for pack in _LOCALE_PACKS
        for phrase in pack.newsletter_phrases
    )
    if (has_marketing or has_newsletter) and not has_price and not has_receipt:
        return False, "marketing_newsletter"

    # --- Positive signals ----------------------------------------------------
    if is_retailer:
        return True, "known_retailer"
    if has_price:
        return True, "price_pattern"
    if has_receipt:
        return True, "receipt_keywords"

    return False, "no_signals"


# ---------------------------------------------------------------------------
# Clothing-likeliness (cheap, pre-LLM) — used to ORDER the extraction queue so
# probable-clothing emails reach the LLM first (first swipeable card in seconds).
# ---------------------------------------------------------------------------
# Garment / apparel words that, in a SUBJECT line, strongly suggest a clothing
# purchase. EN + HE. Substring match against the normalized subject. Kept high-signal
# (no ultra-generic words) so it ranks, not filters — verification is the LLM's job.
_CLOTHING_SUBJECT_WORDS: Tuple[str, ...] = _norm_phrases((
    # EN — generic apparel
    "clothing", "apparel", "fashion", "wardrobe", "outfit", "garment", "wear",
    "activewear", "sportswear", "swimwear", "loungewear", "lingerie", "denim",
    # EN — garments
    "shirt", "t-shirt", "tee", "blouse", "top", "sweater", "hoodie", "sweatshirt",
    "dress", "skirt", "pants", "trousers", "jeans", "shorts", "leggings", "jacket",
    "coat", "blazer", "hoodie", "knit", "cardigan", "jumper", "bra", "underwear",
    "socks", "shoe", "sneaker", "boot", "heel", "sandal", "footwear", "trainers",
    # HE — clothing terms
    "בגד", "ביגוד", "אופנה", "חולצה", "מכנס", "שמלה", "חצאית", "מעיל", "ז'קט",
    "נעל", "נעלי", "סוודר", "גרבי", "תחתון", "חזיי",
))


def clothing_priority(sender: str, subject: str) -> int:
    """Cheap pre-LLM clothing-likeliness rank for the extraction queue.

    Returns 0 (clothing-LIKELY → extract first) when the sender is a known
    clothing/retail brand OR the subject mentions a garment/apparel term; else 1
    (extract after). This only ORDERS the queue — every kept email is still extracted;
    the LLM clothing gate remains authoritative. Sender + subject only; body is not
    inspected (this runs in the fetch hot path where headers are already in hand).
    """
    if is_known_retailer(sender):
        return 0
    subj = _normalize(subject or "")
    if any(w in subj for w in _CLOTHING_SUBJECT_WORDS):
        return 0
    return 1
