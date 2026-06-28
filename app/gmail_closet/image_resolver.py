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
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin
from uuid import UUID

import httpx
from bs4 import BeautifulSoup

from app.gmail_closet.fetch_service import _GMAIL_BASE, _decode_b64, _fetch_one
from app.gmail_closet.image_guard import GuardRejection, guarded_fetch
from app.core.config import settings
from app.gmail_closet.feed_provider import get_feed_provider
from app.gmail_closet.image_guard import FetchBudget, is_allowlisted_host
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

# Inline images smaller than this are almost certainly logos / spacers / tracking
# pixels, not product photos — skip them (mirrors the old extraction threshold).
_MIN_INLINE_BYTES = 4096

# src/alt substrings that mark an <img> as chrome (tracking pixel, spacer, social
# icon, store logo) rather than a product photo. Cheap pre-filter before any fetch.
_NON_PRODUCT_HINTS = (
    "pixel", "spacer", "1x1", "transparent", "beacon", "/track", "tracking",
    "open.aspx", "/o.gif", "facebook", "instagram", "twitter", "tiktok",
    "youtube", "app-store", "google-play", "playstore", "appstore",
)
# Tokens too generic to help match an image to a specific line item.
_STOP = frozenset({
    "the", "and", "for", "with", "size", "color", "colour", "your", "you",
    "men", "women", "mens", "womens", "kids", "set", "pack", "new", "item",
    "shop", "buy", "now", "click", "here", "view", "order", "qty",
})


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
class _Stored:
    """An uploaded (or dedup-reused) blob: its storage URL + content hash.

    Carried through the run-scoped cache so a cache hit on the same source still
    yields the sha needed to stage a product_image_cache row.
    """
    url: str
    sha: str


@dataclass
class _Fetched:
    """Resolved image BYTES (pre-upload) — fed to vision-verify before any commit."""
    raw: bytes
    suffix: str
    content_type: str


# ---------------------------------------------------------------------------
# Run-scoped fetched-once cache
# ---------------------------------------------------------------------------

_FAILED = object()  # sentinel: this key was tried and refused/errored — do not retry


class ResolvedImageCache:
    """Thread-safe "resolve each source exactly once" cache for a single run.

    Keyed by the resolved source (remote URL, or ``cid:<msg>:<id>`` for inline). The
    value is the stored Supabase URL on success, None when storage is unavailable, or
    the _FAILED sentinel when the fetch/upload was refused. Per-key locking means two
    items (or two worker threads) that resolve to the SAME url fetch + upload it once.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: Dict[str, object] = {}
        self._keylocks: Dict[str, threading.Lock] = {}

    def _keylock(self, key: str) -> threading.Lock:
        with self._lock:
            kl = self._keylocks.get(key)
            if kl is None:
                kl = threading.Lock()
                self._keylocks[key] = kl
            return kl

    def get_or_create(self, key: str, producer: Callable[[], Optional[str]]) -> Tuple[object, bool]:
        """Return (value, hit). On miss, run ``producer`` once under the key's lock.

        ``producer`` returns the stored URL (or None if storage is unavailable). A
        GuardRejection (or any error) is swallowed and cached as _FAILED so the same
        bad source is never retried within the run.
        """
        with self._lock:
            if key in self._values:
                return self._values[key], True

        with self._keylock(key):
            with self._lock:
                if key in self._values:
                    return self._values[key], True
            try:
                value: object = producer()
            except GuardRejection as exc:
                logger.info("image resolve refused: reason=%s host=%s", exc.reason, exc.host)
                value = _FAILED
            except Exception as exc:  # storage/upload/parse errors — never fatal
                logger.warning("image resolve error: %s", type(exc).__name__)
                value = _FAILED
            with self._lock:
                self._values[key] = value
            return value, False


# ---------------------------------------------------------------------------
# Gmail inline-image primitives (trusted endpoint — no SSRF surface)
# ---------------------------------------------------------------------------

def suffix_for_mime(mime: str) -> Tuple[str, str]:
    """(suffix, content_type) for a Gmail part mime; defaults to png."""
    m = (mime or "").lower()
    if "png" in m:
        return ".png", "image/png"
    if "jpeg" in m or "jpg" in m:
        return ".jpg", "image/jpeg"
    if "webp" in m:
        return ".webp", "image/webp"
    if "gif" in m:
        return ".gif", "image/gif"
    return ".png", "image/png"


def get_attachment_bytes(
    client: httpx.Client, token: str, msg_id: str, attachment_id: str
) -> Optional[bytes]:
    """Fetch one attachment's bytes via the Gmail attachments API.

    This is the SAME trusted Gmail endpoint as the message fetch — NOT an outbound
    fetch of an arbitrary URL from the email, so it carries no SSRF surface.
    """
    import base64

    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = client.get(
            f"{_GMAIL_BASE}/messages/{msg_id}/attachments/{attachment_id}",
            headers=headers,
            params={"fields": "data,size"},
            timeout=30.0,
        )
        if resp.status_code != 200:
            return None
        data = resp.json().get("data")
        if not data:
            return None
        pad = "=" * ((4 - len(data) % 4) % 4)
        return base64.urlsafe_b64decode(data + pad)
    except Exception:
        return None


@dataclass
class _InlineImage:
    raw: bytes
    suffix: str
    content_type: str


def extract_inline_images(
    payload: dict, client: httpx.Client, token: str, msg_id: str
) -> Tuple[Dict[str, _InlineImage], List[_InlineImage]]:
    """Collect inline image parts, returning (by_content_id, ordered_list).

    ``by_content_id`` maps the part's Content-ID (with surrounding <>/cid: stripped)
    to its bytes, so an HTML ``<img src="cid:...">`` can be matched to its part.
    ``ordered_list`` is every qualifying inline image in document order (the fallback
    when the HTML carries no usable cid reference). Tiny images are dropped.
    """
    by_cid: Dict[str, _InlineImage] = {}
    ordered: List[_InlineImage] = []

    def _content_id(node: dict) -> Optional[str]:
        for h in node.get("headers", []) or []:
            if (h.get("name", "") or "").lower() == "content-id":
                return (h.get("value", "") or "").strip().strip("<>").strip()
        return None

    def _walk(node: dict) -> None:
        mime = node.get("mimeType", "") or ""
        body = node.get("body", {}) or {}
        if mime.lower().startswith("image/"):
            raw: Optional[bytes] = None
            data = body.get("data")
            attachment_id = body.get("attachmentId")
            if data:
                try:
                    import base64
                    pad = "=" * ((4 - len(data) % 4) % 4)
                    raw = base64.urlsafe_b64decode(data + pad)
                except Exception:
                    raw = None
            elif attachment_id:
                raw = get_attachment_bytes(client, token, msg_id, attachment_id)
            if raw and len(raw) >= _MIN_INLINE_BYTES:
                suffix, ctype = suffix_for_mime(mime)
                img = _InlineImage(raw=raw, suffix=suffix, content_type=ctype)
                ordered.append(img)
                cid = _content_id(node)
                if cid:
                    by_cid[cid] = img
        for part in node.get("parts", []) or []:
            _walk(part)

    _walk(payload)
    return by_cid, ordered


# ---------------------------------------------------------------------------
# Raw HTML extraction (the receipt markup we parse for <img>/<a>)
# ---------------------------------------------------------------------------

def extract_html(payload: dict) -> str:
    """Concatenate the raw text/html parts of a Gmail payload (NOT get_text)."""
    html: List[str] = []

    def _walk(node: dict) -> None:
        mime = node.get("mimeType", "")
        body = node.get("body", {})
        data = body.get("data")
        if data and not body.get("attachmentId") and mime == "text/html":
            try:
                html.append(_decode_b64(data))
            except Exception:
                pass
        for part in node.get("parts", []):
            _walk(part)

    _walk(payload)
    return "\n".join(html)


# ---------------------------------------------------------------------------
# DOM association: map <img>/<a> to line items by proximity
# ---------------------------------------------------------------------------

@dataclass
class _ImgCand:
    kind: str            # 'cid' | 'remote'
    ref: str             # content-id (cid) or absolute https url (remote)
    alt: str
    context: str         # text of the nearest block ancestor
    link: Optional[str]  # nearest enclosing/sibling product <a href> (https)


@dataclass
class _ItemRefs:
    """Resolved, ordered candidate sources for one item, in tier order."""
    inline_cids: List[str] = field(default_factory=list)
    remote_imgs: List[str] = field(default_factory=list)
    product_links: List[str] = field(default_factory=list)


def _is_http(url: Optional[str]) -> bool:
    return bool(url) and url.strip().lower().startswith(("http://", "https://"))


def _tokens(s: str) -> set:
    return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(t) >= 3 and t not in _STOP}


def _price_variants(price: Optional[float]) -> List[str]:
    if price is None:
        return []
    try:
        p = float(price)
    except (TypeError, ValueError):
        return []
    out = {f"{p:.2f}", f"{p:.2f}".replace(".", ",")}
    if p == int(p):
        out.add(str(int(p)))
    return [v for v in out if v]


def _nearest_block(tag) -> Optional[object]:
    return tag.find_parent(["td", "li", "div", "tr", "table"])


def _collect_img_candidates(soup: BeautifulSoup) -> List[_ImgCand]:
    """Every product-plausible <img>, with its alt, block-text context and product link."""
    cands: List[_ImgCand] = []
    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        if not src or src.lower().startswith("data:"):
            continue
        low = src.lower()
        alt = (img.get("alt") or "").strip()
        # Skip declared 1px tracking/spacer images and obvious chrome.
        if str(img.get("width", "")).strip() in ("0", "1") or str(img.get("height", "")).strip() in ("0", "1"):
            continue
        if any(h in low for h in _NON_PRODUCT_HINTS) or "logo" in alt.lower():
            continue

        if low.startswith("cid:"):
            kind, ref = "cid", src[4:].strip().strip("<>")
        elif low.startswith("https://"):
            kind, ref = "remote", src
        else:
            continue  # http:// and anything else are refused by the guard anyway

        block = _nearest_block(img)
        context = block.get_text(" ", strip=True) if block else ""
        anchor = img.find_parent("a", href=True)
        link = None
        if anchor and _is_http(anchor.get("href")):
            link = anchor["href"].strip()
        elif block:
            a = block.find("a", href=True)
            if a and _is_http(a.get("href")):
                link = a["href"].strip()
        cands.append(_ImgCand(kind=kind, ref=ref, alt=alt, context=context, link=link))
    return cands


def _score(item: ResolverItem, cand: _ImgCand) -> int:
    item_toks = _tokens(item.name)
    if item.color:
        item_toks |= _tokens(item.color)
    cand_toks = _tokens(cand.alt) | _tokens(cand.context)
    score = len(item_toks & cand_toks)
    # Alt text that IS the product name is a very strong signal.
    if item_toks and item_toks <= _tokens(cand.alt):
        score += 3
    haystack = f"{cand.alt} {cand.context}"
    if any(pv in haystack for pv in _price_variants(item.unit_price)):
        score += 2
    return score


def associate(html: str, items: List[ResolverItem]) -> List[_ItemRefs]:
    """Per-item ordered candidate sources, associated to items by DOM proximity.

    Greedy assignment: the highest-scoring (item, image) pairs claim images first, so
    each <img> backs at most one item. A single-item email with no token match falls
    back to using every product-plausible image/link in document order.
    """
    refs = [_ItemRefs() for _ in items]
    if not html or not items:
        return refs

    soup = BeautifulSoup(html, "html.parser")
    cands = _collect_img_candidates(soup)
    if not cands:
        return refs

    pairs: List[Tuple[int, int, int]] = []  # (score, item_idx, cand_idx)
    for ii, item in enumerate(items):
        for ci, cand in enumerate(cands):
            s = _score(item, cand)
            if s > 0:
                pairs.append((s, ii, ci))
    pairs.sort(key=lambda p: (-p[0], p[1], p[2]))

    used: set = set()
    assigned: Dict[int, List[int]] = {ii: [] for ii in range(len(items))}
    for _s, ii, ci in pairs:
        if ci in used:
            continue
        used.add(ci)
        assigned[ii].append(ci)

    # Single-item fallback: no token overlap anywhere -> take everything in order.
    if len(items) == 1 and not assigned[0]:
        assigned[0] = list(range(len(cands)))

    for ii in range(len(items)):
        r = refs[ii]
        for ci in assigned[ii]:
            cand = cands[ci]
            if cand.kind == "cid":
                if cand.ref not in r.inline_cids:
                    r.inline_cids.append(cand.ref)
            else:
                if cand.ref not in r.remote_imgs:
                    r.remote_imgs.append(cand.ref)
            if cand.link and cand.link not in r.product_links:
                r.product_links.append(cand.link)
    return refs


# ---------------------------------------------------------------------------
# og:image extraction (Tier 3, second hop source)
# ---------------------------------------------------------------------------

def extract_og_image(html: str, base_url: str) -> Optional[str]:
    """Pull the best social/product image URL off a product page's <head>."""
    soup = BeautifulSoup(html, "html.parser")
    for key in ("og:image:secure_url", "og:image", "twitter:image", "twitter:image:src"):
        tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
        if tag and tag.get("content", "").strip():
            return urljoin(base_url, tag["content"].strip())
    link = soup.find("link", rel="image_src")
    if link and link.get("href", "").strip():
        return urljoin(base_url, link["href"].strip())
    return None


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _upload(storage_client, user_id: UUID, raw: bytes, suffix: str, content_type: str) -> Optional[_Stored]:
    if storage_client is None:
        return None
    # Content-addressed dedup: identical bytes (this run, a prior run, or any user)
    # reuse the existing stored URL instead of uploading a fresh blob — stops the
    # orphaned-blob accumulation. The actual PUT is deferred to the callable and
    # runs at most once per distinct image. Single upload chokepoint for all tiers,
    # so the inline -> email-img -> cache -> og:image waterfall order is unchanged.
    from app.utils.image_blob_store import get_or_upload, sha256_hex

    url = get_or_upload(
        raw,
        lambda: storage_client.upload_bytes(
            raw,
            folder=f"ingest_items/{user_id}",
            content_type=content_type,
            suffix=suffix,
        ),
    )
    if not url:
        return None
    return _Stored(url=url, sha=sha256_hex(raw))


# ---------------------------------------------------------------------------
# The resolver
# ---------------------------------------------------------------------------

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
