"""Per-item product-image resolution from an already-fetched receipt email.

This is the email-embedded image layer of the Phase-3 image waterfall. Given a
Gmail message payload (already fetched via the trusted Gmail API) and the line
items extracted from it, resolve ONE real product image per item by trying, in
strict order:

  Tier 1  inline   — an inline image part (``<img src="cid:...">``) associated with
                     the item by DOM proximity, fetched from the Gmail attachments
                     API (trusted endpoint, NO SSRF surface).
  Tier 2  email-img— the item's embedded remote product-image URL
                     (``<img src="https://...">``) associated by DOM proximity and
                     GUARD-FETCHED through image_guard (SSRF-hardened).
  Tier 3  cache    — the shared, cross-user product-image cache
                     (product_image_cache). Serves ONLY verified rows; a DB lookup,
                     no network — sits before the expensive og:image hop. Until the
                     vision-verify wave flips rows to verified it is a safe no-op.
  Tier 4  og:image — the item's product LINK (``<a href="https://...">``):
                     GUARD-FETCH the product page, read ``og:image``, then
                     GUARD-FETCH that image URL. BOTH hops are guarded.

The first tier that yields real image bytes wins; the bytes are uploaded to
Supabase storage (content-addressed dedup via image_blobs) and the resulting URL is
what gets written to ingest_candidates.image_url / clothing_items.image_url. A
run-scoped cache keyed by the resolved URL guarantees the same image is fetched +
uploaded at most once. Every real resolution also STAGES an unverified
product_image_cache row (verified=false) for later vision-verify — staged rows do
NOT serve.

NOTHING here trusts the email enough to fetch on its own — every remote fetch goes
through ``image_guard.guarded_fetch``. Inline (cid) bytes come only from the Gmail
API. Subjects/bodies/full-URLs are never logged.

PACKAGE LAYOUT (P3.7 split of the former single-file god-module, ARCHITECTURE_AUDIT
R9 -- 795 lines, ~5 mixed concerns). Each concern is now its own focused unit
behind this stable public interface:
  _cache.py    -- ResolvedImageCache: run-scoped "resolve each source once" memo.
  _inline.py   -- Gmail inline-image primitives (trusted endpoint, no SSRF surface).
  _html.py     -- HTML extraction, DOM association (item <-> <img>/<a> proximity
                  scoring), and og:image parsing off a product page's <head>.
  _storage.py  -- content-addressed upload (the single chokepoint every tier calls).
  resolve.py   -- the waterfall orchestrator (resolve_item_images) + public
                  datatypes (ResolverItem, ResolvedImage) + the tier-order
                  constants + the guard-fetch helpers only the orchestrator uses.

`from app.gmail_closet.image_resolver import ...` is unchanged for every existing
caller: ResolvedImage, ResolvedImageCache, ResolverItem, resolve_item_images,
ALL_TIERS, FAST_TIERS, SLOW_TIERS, associate, and extract_og_image are all
re-exported here exactly as they were importable from the single module before
the split.
"""
from app.gmail_closet.image_resolver.resolve import (
    ALL_TIERS,
    FAST_TIERS,
    SLOW_TIERS,
    ResolvedImage,
    ResolverItem,
    resolve_item_images,
)
from app.gmail_closet.image_resolver._cache import ResolvedImageCache
from app.gmail_closet.image_resolver._html import associate, extract_og_image

__all__ = [
    "ResolvedImage",
    "ResolvedImageCache",
    "ResolverItem",
    "resolve_item_images",
    "ALL_TIERS",
    "FAST_TIERS",
    "SLOW_TIERS",
    "associate",
    "extract_og_image",
]
