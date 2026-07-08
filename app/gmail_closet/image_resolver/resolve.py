"""The waterfall orchestrator (P3.7 split of the image_resolver god-module).

Given a Gmail message payload and its line items, resolve ONE real product
image per item by trying, in strict order: inline -> email-img -> cache ->
og:image -> feed -> search. See the package docstring
(app/gmail_closet/image_resolver/__init__.py) for the full tier description
and the trust/verify model.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional
from uuid import UUID

import httpx

from app.core.config import settings
from app.gmail_closet.feed_provider import get_feed_provider
from app.gmail_closet.image_guard import FetchBudget, GuardRejection, guarded_fetch, is_allowlisted_host
from app.gmail_closet.image_resolver._cache import _FAILED, ResolvedImageCache
from app.gmail_closet.image_resolver._html import associate, extract_html, extract_og_image
from app.gmail_closet.image_resolver._inline import extract_inline_images
from app.gmail_closet.image_resolver._storage import _Stored, _upload
from app.gmail_closet.image_verify import VerifyBudget, verify_image
from app.gmail_closet.product_image_cache import (
    lookup_verified,
    make_cache_key,
    promote_verified,
    stage_candidate,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Latency tiers (Phase 4: split blocking extraction from background fill)
# ---------------------------------------------------------------------------
# FAST tiers are cheap enough to run INLINE during extraction so the swipe deck
# appears with images already attached: inline (Gmail-API bytes), email-img (one
# guarded fetch of an embedded URL), and CACHE (a verified-only DB lookup, no
# network). SLOW tiers do real outbound work — fetch a product page for og:image,
# hit a product feed, or run a paid shopping search — and are deferred to the
# background image-fill worker, which streams them onto cards as they resolve.
# CACHE is in BOTH sets: it's the ~0-cost first hop the background/self-heal pass
# tries before any network, so an item another user already resolved fills instantly.
FAST_TIERS = frozenset({"inline", "email-img", "cache"})
SLOW_TIERS = frozenset({"cache", "og:image", "feed", "search"})
ALL_TIERS = frozenset({"inline", "email-img", "cache", "og:image", "feed", "search"})


# ---------------------------------------------------------------------------
# Public datatypes
# ---------------------------------------------------------------------------

@dataclass
class ResolverItem:
    """The minimal item descriptor the resolver needs to do DOM association.

    Built from an ExtractedItem (extraction path) or a ClothingItem (backfill path).
    """
    name: str
    unit_price: Optional[float] = None
    color: Optional[str] = None
    size: Optional[str] = None
    brand: Optional[str] = None      # needed for the shared product-image cache key
    category: Optional[str] = None   # garment type — fed to the vision-verify gate


@dataclass
class ResolvedImage:
    """Outcome for one item. ``tier`` is 'inline'|'email-img'|'cache'|'og:image'|'none'."""
    tier: str
    stored_url: Optional[str] = None   # Supabase URL when uploaded; None if no storage
    detail: str = ""                   # short, redaction-safe (host / cid), for reports


@dataclass
class _Fetched:
    """Resolved image BYTES (pre-upload) — fed to vision-verify before any commit."""
    raw: bytes
    suffix: str
    content_type: str


def resolve_item_images(
    *,
    payload: dict,
    items: List[ResolverItem],
    client: httpx.Client,
    token: str,
    msg_id: str,
    storage_client,
    cache: ResolvedImageCache,
    user_id: UUID,
    verify_budget: Optional[VerifyBudget] = None,
    fetch_budget: Optional[FetchBudget] = None,
    search_budget=None,
    tiers: Optional[frozenset] = None,
    usage=None,
) -> List[ResolvedImage]:
    """Resolve one image per item: inline -> email-img -> CACHE -> og:image -> FEED -> SEARCH.

    ``tiers`` selects WHICH tiers run (a subset of ALL_TIERS), in the canonical order
    above; the default (None) runs every tier (the backfill/manual path). Phase 4
    passes ``FAST_TIERS`` during blocking extraction (inline/email-img/cache only — the
    deck must not wait on a network hop) and ``SLOW_TIERS`` from the background
    image-fill worker (cache/og:image/feed/search). A disabled tier is simply skipped;
    the per-item fall-through is otherwise unchanged.

    Every NON-cache resolution (inline, email-img, og:image, and the Tier-5 shopping
    SEARCH) is VISION-VERIFIED before it is trusted: an image is committed only if it
    actually shows the item's garment type + color. A verify FAIL rejects the source
    and falls through to the next tier; if nothing passes, image_url stays None and
    the caller leaves image_status='pending'. A verify PASS commits the image and
    flips its product_image_cache row to verified=true (now serves cross-user). Tier 3
    (CACHE) serves only already-verified rows and is therefore NOT re-verified.

    Tier 5 queries DataForSEO Google Shopping for retailer product pages and resolves
    each page's OWN first-party og:image (never a search-API/Google thumbnail). Hosts
    not on the static allow-list are fetched with the SSRF guard's 'open' profile
    (allow-list gate dropped; all other guards intact), and verify is MANDATORY there.

    When verify is DISABLED in config (e.g. dev without GEMINI_API_KEY) the gate is
    skipped for the EMAIL tiers: the resolved image is committed but only STAGED
    (verified=false), shown to its owner yet never served cross-user. The SEARCH tier
    does NOT run without verify.

    Uploading is content-addressed (image_blobs) and memoized per source via the
    run-scoped ``cache``; every remote hop is SSRF-guarded. ``verify_budget`` caps
    verify calls, ``fetch_budget`` is the per-run outbound-fetch ceiling
    (anti-amplification), and ``search_budget`` caps shopping-search queries.
    """
    results: List[ResolvedImage] = [ResolvedImage(tier="none") for _ in items]
    if not items:
        return results

    tiers = ALL_TIERS if tiers is None else tiers

    by_cid, ordered_inline = extract_inline_images(payload, client, token, msg_id)
    html = extract_html(payload)
    refs = associate(html, items)

    verify_enabled = settings.GMAIL_VERIFY_ENABLED

    # Per-MESSAGE fetch memo: a URL referenced by several items (e.g. a shared banner)
    # is downloaded once. Bounded to this email's images, so run memory stays flat.
    fetched: Dict[str, Optional[_Fetched]] = {}

    def _remote(url: str) -> Optional[_Fetched]:
        if url in fetched:
            return fetched[url]
        try:
            f: Optional[_Fetched] = _fetch_image_bytes(client, url, fetch_budget=fetch_budget)
        except GuardRejection as exc:
            logger.info("image fetch refused host=%s reason=%s", exc.host, exc.reason)
            f = None
        except Exception as exc:
            logger.warning("image fetch error (%s)", type(exc).__name__)
            f = None
        fetched[url] = f
        return f

    def _accept(idx, item, ck, tier, fetch: _Fetched, domain, upload_key, require_verify=False) -> bool:
        """VERIFY (unless disabled) then commit. Returns True iff the image is taken.

        Verify runs on the BYTES, per item — so a shared image that is right for one
        line and wrong for another (the banner bug) passes for the right line only.
        ``require_verify`` forces the gate even when verify is globally disabled — the
        open-profile shopping-search tier sets it so an untrusted web image is NEVER
        committed without a verify pass.
        """
        verdict = None
        if verify_enabled or require_verify:
            verdict = verify_image(
                image_bytes=fetch.raw, content_type=fetch.content_type,
                category=item.category, color=item.color, name=item.name,
                budget=verify_budget, usage=usage,
            )
            if not verdict.matches:
                return False  # rejected (or skipped) -> try the next source / tier

        value, _hit = cache.get_or_create(
            upload_key,
            lambda: _upload(storage_client, user_id, fetch.raw, fetch.suffix, fetch.content_type),
        )
        if value is _FAILED:
            return False
        stored = value if isinstance(value, _Stored) else None
        results[idx] = ResolvedImage(
            tier=tier, stored_url=(stored.url if stored else None), detail=domain
        )
        if stored and ck:
            if verdict is not None:   # verified -> may serve cross-user
                promote_verified(
                    brand=item.brand, name=item.name, color=item.color,
                    image_url=stored.url, content_sha256=stored.sha,
                    source_tier=tier, source_domain=domain, verify_score=verdict.score,
                )
            else:                     # verify disabled -> stage unverified (never serves)
                stage_candidate(
                    brand=item.brand, name=item.name, color=item.color,
                    image_url=stored.url, content_sha256=stored.sha,
                    source_tier=tier, source_domain=domain,
                )
        return True

    for idx, item in enumerate(items):
        r = refs[idx]
        ck = make_cache_key(item.brand, item.name, item.color)

        # --- Tier 1: inline (cid) — verify-gated ---------------------------
        if "inline" in tiers:
            accepted = False
            # Fallback: one inline image, one item, no explicit cid match -> use it.
            if not r.inline_cids and len(items) == 1 and len(ordered_inline) == 1 and not by_cid:
                c = ordered_inline[0]
                if _accept(idx, item, ck, "inline",
                           _Fetched(c.raw, c.suffix, c.content_type), "cid", f"cid:{msg_id}:__only__"):
                    continue
            for cid in r.inline_cids:
                img = by_cid.get(cid)
                if img is None:
                    continue
                if _accept(idx, item, ck, "inline",
                           _Fetched(img.raw, img.suffix, img.content_type), "cid", f"cid:{msg_id}:{cid}"):
                    accepted = True
                    break
            if accepted:
                continue

        # --- Tier 2: embedded remote product-image URL (GUARD-FETCHED + verify) ---
        if "email-img" in tiers:
            accepted = False
            for url in r.remote_imgs:
                f = _remote(url)
                if f is None:
                    continue
                host = httpx.URL(url).host or ""
                if _accept(idx, item, ck, "email-img", f, host, url):
                    accepted = True
                    break
            if accepted:
                continue

        # --- Tier 3: shared product-image cache (serves VERIFIED rows only) -
        # Already-verified rows; NOT re-verified. Read-only serve, no staging. Cheap
        # (a DB lookup, no network), so it is the FIRST hop of the background/self-heal
        # SLOW pass too: an item another user already resolved fills here at ~0 cost.
        if "cache" in tiers:
            cache_hit = lookup_verified(ck)
            if cache_hit:
                results[idx] = ResolvedImage(tier="cache", stored_url=cache_hit, detail="verified-cache")
                continue

        # --- Tier 4: product link -> og:image (BOTH hops GUARD-FETCHED + verify) ---
        if "og:image" in tiers:
            accepted = False
            for link in r.product_links:
                try:
                    f = _fetch_og_bytes(client, link, fetch_budget=fetch_budget)
                except GuardRejection as exc:
                    logger.info("og fetch refused host=%s reason=%s", exc.host, exc.reason)
                    continue
                except Exception as exc:
                    logger.warning("og fetch error (%s)", type(exc).__name__)
                    continue
                host = httpx.URL(link).host or ""
                if _accept(idx, item, ck, "og:image", f, host, f"og:{link}"):
                    accepted = True
                    break
            if accepted:
                continue

        # --- Tier 4.5: pluggable product feed (Sovrn/Awin/… — stub seam) ---
        # Behind GMAIL_FEED_ENABLED; ships as NullFeedProvider (always misses). The feed
        # returns a URL ONLY; we guard-fetch it (open profile off the allow-list) and
        # require_verify=True so an untrusted feed image is NEVER committed without a
        # vision-verify pass — identical trust handling to the search tier.
        if "feed" in tiers and settings.GMAIL_FEED_ENABLED:
            fr = get_feed_provider().lookup(item.brand, item.name, item.color)
            if fr and fr.image_url:
                fhost = httpx.URL(fr.image_url).host or ""
                fprofile = "retailer" if is_allowlisted_host(fhost) else "open"
                f = None
                try:
                    f = _fetch_image_bytes(client, fr.image_url, profile=fprofile, fetch_budget=fetch_budget)
                except GuardRejection as exc:
                    logger.info("feed fetch refused host=%s reason=%s profile=%s",
                                exc.host, exc.reason, fprofile)
                except Exception as exc:
                    logger.warning("feed fetch error (%s)", type(exc).__name__)
                if f is not None and _accept(
                    idx, item, ck, "feed", f, (fr.source_domain or fhost),
                    f"feed:{fr.image_url}", require_verify=True,
                ):
                    continue

        # --- Tier 5: long-tail shopping search (DataForSEO) ----------------
        if "search" not in tiers:
            continue
        # Search needs vision-verify (web images are untrusted); if verify is off, do
        # NOT run it — leave the item pending. One search query per item, capped by
        # search_budget. For each ranked retailer link we resolve the page's OWN
        # og:image (first-party; never a DataForSEO/Google thumbnail), open-profile if
        # the host isn't allow-listed, then MANDATORY verify before commit.
        if not (settings.GMAIL_SEARCH_ENABLED and settings.GMAIL_VERIFY_ENABLED):
            continue
        from app.gmail_closet.shopping_search import search_products

        candidates = search_products(item.brand, item.name, item.color, budget=search_budget, usage=usage)
        for cand in candidates[: settings.GMAIL_SEARCH_MAX_CANDIDATES]:
            host = httpx.URL(cand.url).host or ""
            profile = "retailer" if is_allowlisted_host(host) else "open"
            try:
                f = _fetch_og_bytes(client, cand.url, profile=profile, fetch_budget=fetch_budget)
            except GuardRejection as exc:
                logger.info("search fetch refused host=%s reason=%s profile=%s",
                            exc.host, exc.reason, profile)
                continue
            except Exception as exc:
                logger.warning("search fetch error (%s)", type(exc).__name__)
                continue
            # LICENSE: f is the retailer page's OWN og:image (first-party). source_domain
            # is the retailer/seller domain. require_verify=True -> never commit an
            # open-profile web image without a verify pass.
            if _accept(idx, item, ck, "search", f, cand.source_domain or host,
                       f"search:{cand.url}", require_verify=True):
                break

    return results


def _fetch_image_bytes(client, url, *, profile="retailer", fetch_budget=None) -> _Fetched:
    """Guard-fetch a remote image; return its BYTES (no upload). Raises GuardRejection.

    Upload is deferred until AFTER vision-verify passes, so junk/mis-associated images
    are never stored. ``profile``/``fetch_budget`` are passed straight to the guard.
    """
    res = guarded_fetch(client, url, kind="image", profile=profile, fetch_budget=fetch_budget)
    return _Fetched(raw=res.content, suffix=res.suffix, content_type=res.content_type)


def _fetch_og_bytes(client, link, *, profile="retailer", fetch_budget=None) -> _Fetched:
    """Guard-fetch a product page, read og:image, then guard-fetch that image's BYTES.

    BOTH hops are guarded (with the SAME ``profile`` and shared ``fetch_budget``);
    nothing is uploaded here (verify gates upload). For a shopping-search candidate on
    a non-allowlisted host this runs under profile='open' — the og:image it returns is
    the RETAILER's own first-party image, never a search-API/Google thumbnail. Raises
    GuardRejection on refusal or when the page has no og:image.
    """
    page = guarded_fetch(client, link, kind="html", profile=profile, fetch_budget=fetch_budget)
    html = page.content.decode("utf-8", errors="ignore")
    og_url = extract_og_image(html, f"https://{page.final_host}/")
    if not og_url:
        raise GuardRejection("not_image", page.final_host, "no og:image")
    img = guarded_fetch(client, og_url, kind="image", profile=profile, fetch_budget=fetch_budget)
    return _Fetched(raw=img.content, suffix=img.suffix, content_type=img.content_type)
