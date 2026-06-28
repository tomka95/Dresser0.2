"""Shared, cross-user product-image cache (Wave 2a) — resolve-once-serve-many.

This module owns BOTH:
  * the cache_key NORMALIZATION (make_cache_key + the normalize helpers), and
  * the cache READ (lookup_verified) / WRITE (stage_candidate) against the
    product_image_cache table.

SAFETY MODEL (why this can't serve a wrong / cross-user image)
-------------------------------------------------------------
  * READ serves ONLY rows with verified = true. WRITE here stages ONLY
    verified = false rows. Nothing in Wave 2a ever sets verified = true — only the
    later vision-verify wave (2b) does. So until 2b ships, lookup_verified always
    returns nothing: the read tier is a guaranteed no-op.
  * The staging upsert NEVER touches an already-verified row (ON CONFLICT ... WHERE
    NOT verified), so a later unverified resolution cannot un-verify or overwrite a
    trusted row.
  * The table holds product-catalog data only — no user_id, no message/order ids —
    so a served row carries nothing user-specific. Serving a verified product image
    to many users is the intended catalog byproduct, not a leak.

CACHE-KEY NORMALIZATION (deterministic, documented, CONSERVATIVE)
----------------------------------------------------------------
A wrong collision serves a wrong image cross-user, so we bias toward a near-miss
(cache miss) over a false merge: we strip only high-confidence boilerplate and keep
the full discriminating product core.

  cache_key = sha256( "v1" |US| normalize_brand(brand)
                            |US| normalize_name(name, brand)
                            |US| canonical_color(color) )            (|US| = \x1f)

  normalize_brand:  lower, trim, collapse whitespace, drop punctuation.
  normalize_name:   lower, trim, collapse whitespace, drop surrounding quotes;
                    strip a leading brand / known SHEIN-family sub-brand prefix;
                    TRUNCATE the SHEIN-style marketing tail at the earliest
                    occasion/season marker ("... for autumn/winter, going out, ..."
                    -> dropped); remove apostrophes, drop remaining punctuation.
  canonical_color:  lower, trim, collapse; SPELLING/format synonyms only
                    (grey->gray, navy blue->navy, multicolour->multi). We do NOT
                    merge near-colors — color is exactly what distinguishes product
                    variants, so merging "light blue" into "blue" would serve the
                    wrong variant image. Conservative on purpose.

If the normalized name is empty we return None (no key): keying on brand+color
alone is too generic and would risk false merges, so such items are simply not
cached.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = logging.getLogger(__name__)

# Bump when the normalization scheme changes so old keys never collide with new.
KEY_VERSION = "v1"
_FIELD_SEP = "\x1f"  # unit separator — can't appear in product text

_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")

# Leading brand-family prefixes peeled off a name before keying. The item's own
# brand is also peeled (handled in normalize_name); these cover SHEIN's house
# sub-brands that show up inside the NAME even when brand == "SHEIN".
_SUBBRAND_PREFIXES = (
    "shein ", "shein x ", "ezwear ", "shein ezwear ", "shein basics ",
    "shein curve ", "shein priv ", "dazy ", "romwe ", "luvlette ", "emery rose ",
    "motf ", "glowmode ",
)

# SHEIN-style marketing tail: the product core comes FIRST, then occasion/season
# marketing. We truncate the name at the EARLIEST marker so the discriminating core
# is preserved and distinct products keep distinct keys.
_OCCASION = (
    "spring|summer|autumn|fall|winter|everyday|daily|going out|work|office|casual|"
    "party|vacation|holiday|beach|home|sport|sports|gym|travel|date|club|"
    "night out|street|streetwear|formal|outdoor|lounge|loungewear"
)
_TAIL = re.compile(
    r"\b(?:for|suitable for|perfect for|ideal for|great for|good for)\s+"
    r"(?:" + _OCCASION + r")\b"
    r"|,\s*(?:" + _OCCASION + r")\b"
)

# SHEIN-style titles also append a long occasion/marketing LIST with neither a "for"
# nor a comma trigger (e.g. "... denim jacket spring summer streetwear the book shop
# concert festival back to school work office fall winter casual christmas chic").
# We collapse such a tail by cutting at the first RUN of >= _MARKETING_RUN_MIN
# consecutive marketing/occasion words. Built from the _OCCASION vocabulary (single
# words only) plus common holiday/marketing fillers. A lone marketing word (e.g.
# "summer dress", "party top") is kept — only a run is treated as a tail.
_MARKETING_WORDS = frozenset(
    w for phrase in _OCCASION.split("|") for w in phrase.split()
) | frozenset({
    "streetwear", "concert", "festival", "wedding", "birthday", "school",
    "christmas", "thanksgiving", "halloween", "valentine", "valentines",
    "easter", "newyear", "chic", "trendy", "stylish", "fashionable", "fashion",
    "gift", "gifts", "cute", "classic", "vintage", "elegant", "aesthetic",
})
_MARKETING_RUN_MIN = 3
# Backstop caps so a pathological title can't blow up the cache key / search query.
_MAX_NAME_TOKENS = 12
_MAX_NAME_CHARS = 80

# Color SPELLING/format synonyms only (never near-color merges). Applied as a
# whole-string match first, then per word (so "dark grey" -> "dark gray").
_COLOR_SYNONYMS = {
    "grey": "gray",
    "navy blue": "navy",
    "off-white": "off white",
    "offwhite": "off white",
    "multicolour": "multi",
    "multicolor": "multi",
    "multi colour": "multi",
    "multi color": "multi",
    "colour": "color",
}


def _basic(s: Optional[str]) -> str:
    """Lower, strip, drop surrounding quotes, collapse internal whitespace."""
    s = (s or "").strip().lower().strip("\"'")
    return _WS.sub(" ", s).strip()


def normalize_brand(brand: Optional[str]) -> str:
    s = _basic(brand)
    s = _NON_ALNUM.sub(" ", s)
    return _WS.sub(" ", s).strip()


def _truncate_marketing_run(s: str) -> str:
    """Cut ``s`` at the first run of >= _MARKETING_RUN_MIN consecutive marketing words.

    Preserves the product core before the run; a lone marketing word never triggers a
    cut. Won't cut at index 0 (so an all-marketing string is left for the cap to trim).
    """
    toks = s.split()
    run = 0
    for i, t in enumerate(toks):
        if t in _MARKETING_WORDS:
            run += 1
            if run >= _MARKETING_RUN_MIN:
                start = i - run + 1
                if start >= 1:
                    return " ".join(toks[:start])
        else:
            run = 0
    return s


def _cap_name(s: str) -> str:
    """Backstop: cap to _MAX_NAME_TOKENS / _MAX_NAME_CHARS, never splitting a word."""
    toks = s.split()
    if len(toks) > _MAX_NAME_TOKENS:
        toks = toks[:_MAX_NAME_TOKENS]
    s = " ".join(toks)
    if len(s) > _MAX_NAME_CHARS:
        s = s[:_MAX_NAME_CHARS].rsplit(" ", 1)[0]
    return s.strip()


def normalize_name(name: Optional[str], brand: Optional[str] = None) -> str:
    s = _basic(name)
    if not s:
        return ""

    # Peel a leading brand prefix (so brand isn't double-counted in the key).
    b = _basic(brand)
    if b and s.startswith(b + " "):
        s = s[len(b) + 1:]
    # Peel one known SHEIN-family sub-brand prefix.
    for p in _SUBBRAND_PREFIXES:
        if s.startswith(p):
            s = s[len(p):]
            break

    # Truncate the marketing tail at the earliest occasion/season marker.
    m = _TAIL.search(s)
    if m:
        s = s[:m.start()]

    # Remove apostrophes (women's -> womens), then drop remaining punctuation.
    s = s.replace("’", "").replace("'", "")
    s = _NON_ALNUM.sub(" ", s)
    s = _WS.sub(" ", s).strip()

    # Collapse a long marketing LIST tail (no for-/comma trigger), then hard-cap.
    s = _truncate_marketing_run(s)
    return _cap_name(s)


def canonical_color(color: Optional[str]) -> str:
    s = _basic(color)
    s = s.replace("’", "").replace("'", "")
    s = _NON_ALNUM.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    if not s:
        return ""
    if s in _COLOR_SYNONYMS:
        return _COLOR_SYNONYMS[s]
    return " ".join(_COLOR_SYNONYMS.get(w, w) for w in s.split())


def make_cache_key(
    brand: Optional[str], name: Optional[str], color: Optional[str]
) -> Optional[str]:
    """Deterministic product-identity key, or None when it would be unsafe to key.

    Returns None if the normalized name is empty (keying on brand+color alone is too
    generic and risks false cross-user merges).
    """
    nn = normalize_name(name, brand)
    if not nn:
        return None
    nb = normalize_brand(brand)
    nc = canonical_color(color)
    raw = _FIELD_SEP.join((KEY_VERSION, nb, nn, nc))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Cache READ / WRITE (own short-lived session — safe from resolver worker threads)
# ---------------------------------------------------------------------------

def lookup_verified(cache_key: Optional[str]) -> Optional[str]:
    """Return the stored image URL for a VERIFIED cache row, bumping serve stats.

    Serves ONLY verified = true rows. Until Wave 2b verifies rows this returns None
    for everything (safe no-op). Best-effort: never raises into the resolver.
    """
    if not cache_key:
        return None
    try:
        from app.db import SessionLocal
        from app.models import ProductImageCache

        db = SessionLocal()
        try:
            row = (
                db.query(ProductImageCache)
                .filter(
                    ProductImageCache.cache_key == cache_key,
                    ProductImageCache.verified.is_(True),
                )
                .first()
            )
            if row is None:
                return None
            row.serve_count = (row.serve_count or 0) + 1
            row.last_served_at = datetime.now(timezone.utc)
            db.commit()
            return row.image_url
        finally:
            db.close()
    except Exception as exc:  # never let a cache read break resolution
        logger.warning("product_image_cache lookup failed: %s", type(exc).__name__)
        return None


def stage_candidate(
    *,
    brand: Optional[str],
    name: Optional[str],
    color: Optional[str],
    image_url: Optional[str],
    content_sha256: Optional[str],
    source_tier: str,
    source_domain: str,
) -> None:
    """Upsert an UNVERIFIED (verified = false) staging row for a resolved image.

    Staged rows DO NOT serve (lookup_verified ignores them). A later vision-verify
    wave reads these and flips the good ones to verified. The upsert never touches
    an already-verified row (ON CONFLICT ... WHERE NOT verified), so a wrong
    resolution can't clobber a trusted one. Best-effort: never raises into the
    resolver.
    """
    cache_key = make_cache_key(brand, name, color)
    if not cache_key or not image_url:
        return
    try:
        from app.db import SessionLocal
        from app.models import ProductImageCache

        tbl = ProductImageCache.__table__
        nb = normalize_brand(brand)
        nn = normalize_name(name, brand)
        nc = canonical_color(color)

        stmt = pg_insert(tbl).values(
            cache_key=cache_key,
            brand=nb,
            name_norm=nn,
            color_norm=nc,
            image_url=image_url,
            content_sha256=content_sha256,
            source_tier=source_tier,
            source_domain=source_domain,
            verified=False,
            serve_count=0,
        )
        ex = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            constraint="product_image_cache_cache_key_key",
            set_={
                "image_url": ex.image_url,
                "content_sha256": ex.content_sha256,
                "source_tier": ex.source_tier,
                "source_domain": ex.source_domain,
            },
            where=(tbl.c.verified.is_(False)),  # NEVER mutate a verified row
        )

        db = SessionLocal()
        try:
            db.execute(stmt)
            db.commit()
        finally:
            db.close()
    except Exception as exc:  # staging is best-effort, never fatal to resolution
        logger.warning("product_image_cache stage failed: %s", type(exc).__name__)


def promote_verified(
    *,
    brand: Optional[str],
    name: Optional[str],
    color: Optional[str],
    image_url: Optional[str],
    content_sha256: Optional[str],
    source_tier: str,
    source_domain: str,
    verify_score: Optional[float],
) -> bool:
    """Insert/flip the product_image_cache row for this product to verified=true.

    Called by the vision-verify gate (Wave 2b) ONLY after an image passes verify, so
    the row may now be served cross-user. This is authoritative: unlike stage_candidate
    it intentionally has no "WHERE NOT verified" guard — a fresh verify is allowed to
    update an existing row's image/url/score (last verified wins). Returns True on a
    successful write. Best-effort: never raises into the caller.

    content_sha256 may be None (e.g. re-verify seeding from an existing stored image
    whose bytes aren't recorded in image_blobs) — the FK is nullable.
    """
    cache_key = make_cache_key(brand, name, color)
    if not cache_key or not image_url:
        return False
    try:
        from app.db import SessionLocal
        from app.models import ProductImageCache

        tbl = ProductImageCache.__table__
        stmt = pg_insert(tbl).values(
            cache_key=cache_key,
            brand=normalize_brand(brand),
            name_norm=normalize_name(name, brand),
            color_norm=canonical_color(color),
            image_url=image_url,
            content_sha256=content_sha256,
            source_tier=source_tier,
            source_domain=source_domain,
            verified=True,
            verify_score=verify_score,
            serve_count=0,
        )
        ex = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            constraint="product_image_cache_cache_key_key",
            set_={
                "image_url": ex.image_url,
                "content_sha256": ex.content_sha256,
                "source_tier": ex.source_tier,
                "source_domain": ex.source_domain,
                "verified": True,
                "verify_score": ex.verify_score,
            },
        )
        db = SessionLocal()
        try:
            db.execute(stmt)
            db.commit()
        finally:
            db.close()
        return True
    except Exception as exc:
        logger.warning("product_image_cache promote failed: %s", type(exc).__name__)
        return False
