"""Wave 2c long-tail shopping search — provider-agnostic (Serper | DataForSEO).

When the cache + email + og tiers all miss, we search Google Shopping for the item by
brand+name+color, collect RETAILER PRODUCT-PAGE LINKS, and hand them back to the
resolver. The resolver then fetches each retailer page and reads ITS OWN og:image
(first-party) — see the license rule below.

PROVIDERS (selected by SEARCH_PROVIDER):
  * 'serper'     — https://google.serper.dev/search (ORGANIC web), header X-API-KEY.
                   Synchronous (no task/poll). Free tier. THE DEFAULT. We use the
                   organic endpoint, not /shopping: /shopping's organic[].link values
                   are Google-redirect URLs (www.google.com/...&udm=28) with no direct
                   retailer URL, so they'd all be dropped. organic[].link values ARE
                   direct retailer product pages the og:image+verify path can consume.
  * 'dataforseo' — Merchant API Google Shopping, Standard async queue (task_post ->
                   poll task_get). HTTP Basic auth.
Both return the SAME ShopCandidate(url, source_domain, title) shape; search_products()
dispatches to the configured one. Hebrew items auto-route to the Israel locale.

LICENSE RULE (enforced by construction, for EVERY provider):
    This module returns LINKS ONLY. It NEVER reads or returns a provider's response
    image fields (imageUrl/thumbnailUrl/…) or Google's cached thumbnails
    (encrypted-tbn*.gstatic.com), and drops google/gstatic/serper/dataforseo hosts.
    The image a closet item ends up with is always resolved first-party from the
    retailer's own page by the resolver, never a search-API/Google thumbnail.

HOST GATING (organic results are noisy):
  * Hard-DROP non-product host classes — social/UGC (instagram, tiktok, pinterest,
    facebook, youtube, reddit…) and C2C/resale (poshmark, thredup, ebay, etsy,
    depop, mercari…) — plus search/listing/brand-landing URLs (amazon "/s?k=",
    SHEIN "/style/…-sc-…"). These never reach the fetch+verify path.
  * RANK known retailers first (RETAILER_DOMAINS + their CDNs via is_allowlisted_host);
    unknown allowed hosts are only a lower-priority fallback. With a small
    GMAIL_SEARCH_MAX_CANDIDATES, the pages we actually fetch are first-party retailers
    whenever a retailer match exists. Vision-verify remains the final backstop.

Opt-in via GMAIL_SEARCH_ENABLED; per-run query cap via SearchBudget. Parsers are
defensive about response shape; an empty result just means the item stays pending.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import List, Optional

import httpx

from app.core.config import settings
from app.gmail_closet.image_guard import is_allowlisted_host
from app.gmail_closet.product_image_cache import normalize_name

logger = logging.getLogger(__name__)

_API_BASE = "https://api.dataforseo.com/v3/merchant/google/products"
_SERPER_URL = "https://google.serper.dev/search"   # ORGANIC web results (see module docstring)
_SERPER_RESULT_KEY = "organic"                       # the key holding result links

# Hosts that are NEVER retailer product pages (search-engine / thumbnail / API hosts).
_BLOCKED_LINK_HOSTS = (
    "google.com", "google.co.il", "googleadservices.com", "gstatic.com",
    "googleusercontent.com", "dataforseo.com", "serper.dev", "schema.org",
)

# Hard-DROP: non-product host CLASSES. Organic /search surfaces these for fashion
# queries, but they are never first-party retailer product pages — drop them so they
# never reach the fetch + verify path (verify still backstops everything else).
_DENY_HOSTS = (
    # social / UGC
    "instagram.com", "tiktok.com", "pinterest.com", "facebook.com", "fb.com",
    "youtube.com", "youtu.be", "reddit.com", "twitter.com", "x.com",
    "snapchat.com", "tumblr.com", "threads.net", "linkedin.com",
    # C2C / resale marketplaces
    "poshmark.com", "thredup.com", "ebay.com", "etsy.com", "depop.com",
    "mercari.com", "vinted.com", "grailed.com", "stockx.com", "goat.com",
)

# Path/query hints of a SEARCH / LISTING / brand-landing page (not a single product),
# e.g. amazon "/s?k=", SHEIN brand listings "/style/...-sc-...". Dropped regardless of
# host so even a known retailer's search page is never fetched as if it were a product.
_LANDING_HINTS = ("/search", "/discover", "/brand/", "/style/", "/sch/", "/s?", "?k=", "&k=", "-sc-")
# Item keys that may carry a retailer PAGE link. We deliberately do NOT read any
# image/thumbnail key (license rule) — only page links.
_LINK_KEYS = ("url", "link", "product_url", "seller_url", "click_url", "shop_url")

_HEBREW = re.compile(r"[֐-׿]")
_ISRAEL_LOCATION_CODE = 2376


@dataclass
class ShopCandidate:
    """A ranked retailer product-page candidate. NEVER carries an image URL."""
    url: str                 # retailer product page (first-party image resolved later)
    source_domain: str       # the retailer/seller domain (recorded as source_domain)
    title: str = ""


class SearchBudget:
    """Per-run cap on shopping-SEARCH queries (cost guard). Thread-safe."""

    def __init__(self, limit: int):
        self._lock = threading.Lock()
        self._remaining = max(0, int(limit))

    def take(self) -> bool:
        with self._lock:
            if self._remaining <= 0:
                return False
            self._remaining -= 1
            return True

    @property
    def remaining(self) -> int:
        with self._lock:
            return self._remaining


# ---------------------------------------------------------------------------
# Query construction + localization
# ---------------------------------------------------------------------------

def _is_hebrew(s: Optional[str]) -> bool:
    return bool(_HEBREW.search(s or ""))


def build_query(brand: Optional[str], name: Optional[str], color: Optional[str]) -> str:
    """Clean shopping query: brand + de-marketed product name + color.

    Reuses the cache normalizer (normalize_name) to strip the SHEIN-style marketing
    tail and brand prefix, so "SHEIN EZwear ... For Autumn/Winter, Going Out" becomes
    the product core. brand and color are appended for colorway disambiguation.
    """
    name_core = normalize_name(name, brand)
    parts: List[str] = []
    b = (brand or "").strip()
    if b:
        parts.append(b)
    if name_core:
        parts.append(name_core)
    c = (color or "").strip()
    if c:
        parts.append(c)
    return " ".join(parts).strip()


def _localize(brand: Optional[str], name: Optional[str]) -> tuple[int, str]:
    """DataForSEO (location_code, language_code). Hebrew -> Israel/he, else default."""
    if _is_hebrew(name) or _is_hebrew(brand):
        return _ISRAEL_LOCATION_CODE, "he"
    return settings.GMAIL_SEARCH_LOCATION_CODE, settings.GMAIL_SEARCH_LANGUAGE_CODE


def _serper_locale(brand: Optional[str], name: Optional[str]) -> tuple[str, str]:
    """Serper (gl, hl). Hebrew text -> Israel/he, else configured default (us/en)."""
    if _is_hebrew(name) or _is_hebrew(brand):
        return "il", "he"
    return settings.GMAIL_SEARCH_GL, settings.GMAIL_SEARCH_LANGUAGE_CODE


# ---------------------------------------------------------------------------
# Response parsing (links only — never image fields)
# ---------------------------------------------------------------------------

def _host(url: str) -> str:
    try:
        return (httpx.URL(url).host or "").lower()
    except Exception:
        return ""


def _is_denied_host(host: str) -> bool:
    """True for social/UGC + C2C/resale hosts that are never first-party product pages."""
    return any(host == d or host.endswith("." + d) for d in _DENY_HOSTS)


def _is_landing_url(url: str) -> bool:
    """True for search / listing / brand-landing URLs (not a single product page)."""
    low = url.lower()
    return any(hint in low for hint in _LANDING_HINTS)


def _is_retailer_link(url: str) -> bool:
    """A link we may CONSIDER: https, real host, not a blocked/denied host, not a
    search/listing landing page. (Ranking still prefers known retailers; verify is the
    final backstop for anything that passes here.)"""
    if not isinstance(url, str) or not url.lower().startswith("https://"):
        return False
    h = _host(url)
    if not h or "." not in h:
        return False
    if any(h == b or h.endswith("." + b) for b in _BLOCKED_LINK_HOSTS):
        return False
    if _is_denied_host(h):
        return False
    if _is_landing_url(url):
        return False
    return True


def _rank_candidates(cands: List[ShopCandidate]) -> List[ShopCandidate]:
    """Stable sort: known retailers (RETAILER_DOMAINS + their CDNs) first, unknown
    allowed hosts after — so the small top-N we actually fetch are first-party retailer
    pages, and unknown hosts are only a lower-priority fallback."""
    return sorted(cands, key=lambda c: 0 if is_allowlisted_host(_host(c.url)) else 1)


def _candidates_from_result(payload: dict) -> List[ShopCandidate]:
    """Pull ranked retailer page links out of a task_get/advanced payload.

    Defensive: walks tasks[].result[].items[] and reads only _LINK_KEYS. Dedups by
    host, preserving DataForSEO's ranking order. Never touches image/thumbnail keys.
    """
    out: List[ShopCandidate] = []
    seen_hosts: set = set()
    for task in (payload.get("tasks") or []):
        for result in (task.get("result") or []):
            for item in (result.get("items") or []):
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "")
                seller = str(item.get("seller") or item.get("domain") or "")
                for key in _LINK_KEYS:
                    link = item.get(key)
                    if not _is_retailer_link(link):
                        continue
                    h = _host(link)
                    if h in seen_hosts:
                        continue
                    seen_hosts.add(h)
                    out.append(ShopCandidate(url=link, source_domain=(seller.lower() or h), title=title))
                    break  # one link per item is enough
    return out


def _candidates_from_serper(payload: dict) -> List[ShopCandidate]:
    """Pull ranked retailer page links out of a Serper /search (organic) response.

    LICENSE: reads ONLY each organic result's 'link' (a direct retailer product page).
    It never touches any image field, and _is_retailer_link drops gstatic/google/serper
    hosts (incl. any google.com redirect). Dedups by host, keeping Serper's ranking
    order. Non-retailer organic hits (blogs, marketplaces we don't recognize, etc.)
    still flow through, but the downstream og:image fetch + mandatory verify reject
    anything that isn't the actual product.
    """
    out: List[ShopCandidate] = []
    seen_hosts: set = set()
    for item in (payload.get(_SERPER_RESULT_KEY) or []):
        if not isinstance(item, dict):
            continue
        link = item.get("link")
        if not _is_retailer_link(link):
            continue
        h = _host(link)
        if h in seen_hosts:
            continue
        seen_hosts.add(h)
        out.append(ShopCandidate(url=link, source_domain=h, title=str(item.get("title") or "")))
    return out


# ---------------------------------------------------------------------------
# The Standard-queue task lifecycle
# ---------------------------------------------------------------------------

def search_products(
    brand: Optional[str],
    name: Optional[str],
    color: Optional[str],
    *,
    budget: Optional[SearchBudget] = None,
    usage=None,
) -> List[ShopCandidate]:
    """Provider-agnostic shopping search → ranked retailer page candidates (links only).

    Dispatches to SEARCH_PROVIDER ('serper' default, or 'dataforseo'). No-ops (returns
    []) when search is disabled, the provider's credentials are missing, the provider
    is unknown, the per-run SearchBudget is exhausted, or anything errors. NEVER raises
    into the resolver. The HTTP error path logs status + redacted body for BOTH
    providers (their APIs return a JSON status/message even on errors).

    ``usage`` (an optional UsageAccumulator) counts one Serper CREDIT per ISSUED Serper
    query — recorded right after the per-run budget is consumed, so it reflects real
    billable calls (not no-ops) for per-sync cost tracking.
    """
    if not settings.GMAIL_SEARCH_ENABLED:
        return []
    provider = (settings.SEARCH_PROVIDER or "serper").strip().lower()

    query = build_query(brand, name, color)
    if not query:
        return []

    # Credential / provider preflight (no budget consumed on misconfiguration).
    if provider == "serper" and not settings.SERPER_API_KEY:
        logger.info("shopping search skipped: SERPER_API_KEY not set")
        return []
    if provider == "dataforseo" and not (settings.DATAFORSEO_LOGIN and settings.DATAFORSEO_PASSWORD):
        logger.info("shopping search skipped: DATAFORSEO credentials not configured")
        return []
    if provider not in ("serper", "dataforseo"):
        logger.warning("shopping search skipped: unknown SEARCH_PROVIDER=%r", provider)
        return []

    # Cost cap: consume one unit per ISSUED query.
    if budget is not None and not budget.take():
        logger.info("shopping search skipped: per-run query budget exhausted")
        return []

    # A query is now being issued (budget consumed, creds present): count the credit.
    # Serper bills one credit per /search query; DataForSEO bills per task (not counted
    # as a Serper credit here).
    if usage is not None and provider == "serper":
        try:
            usage.add_serper(1)
        except Exception:
            pass

    try:
        if provider == "serper":
            candidates = _search_serper(query, brand, name)
        else:
            candidates = _search_dataforseo(query, brand, name)
        # Host gating already dropped denied/landing hosts at parse time; now rank so
        # known retailers are tried before unknown fallback hosts.
        candidates = _rank_candidates(candidates)
        n_retailer = sum(1 for c in candidates if is_allowlisted_host(_host(c.url)))
        logger.info(
            "shopping search [%s]: query_len=%d -> %d candidate(s) (%d retailer, %d fallback)",
            provider, len(query), len(candidates), n_retailer, len(candidates) - n_retailer,
        )
        return candidates
    except httpx.HTTPStatusError as exc:
        # Both providers return a JSON status/message even on HTTP errors — surface the
        # HTTP status + (redacted) body so failures aren't silent.
        resp = exc.response
        body = _redact_secrets(getattr(resp, "text", "") or "")[:500]
        logger.warning(
            "shopping search [%s] HTTP error: status=%s body=%s",
            provider, getattr(resp, "status_code", "?"), body,
        )
        return []
    except Exception as exc:
        logger.warning("shopping search [%s] error (%s)", provider, type(exc).__name__)
        return []


def _search_serper(query: str, brand: Optional[str], name: Optional[str]) -> List[ShopCandidate]:
    """Serper organic /search — synchronous POST, no task/poll. Returns links only."""
    gl, hl = _serper_locale(brand, name)
    headers = {"X-API-KEY": settings.SERPER_API_KEY or "", "Content-Type": "application/json"}
    with httpx.Client(timeout=20.0) as http:
        resp = http.post(_SERPER_URL, headers=headers, json={"q": query, "gl": gl, "hl": hl})
        resp.raise_for_status()
        data = resp.json()
    return _candidates_from_serper(data)


def _search_dataforseo(query: str, brand: Optional[str], name: Optional[str]) -> List[ShopCandidate]:
    """DataForSEO Merchant Google Shopping — Standard async queue (task_post -> poll)."""
    location_code, language_code = _localize(brand, name)
    auth = (settings.DATAFORSEO_LOGIN, settings.DATAFORSEO_PASSWORD)
    with httpx.Client(timeout=20.0) as http:
        post = http.post(
            f"{_API_BASE}/task_post",
            auth=auth,
            json=[{
                "keyword": query,
                "language_code": language_code,
                "location_code": location_code,
            }],
        )
        post.raise_for_status()
        task_id = _extract_task_id(post.json())
        if not task_id:
            logger.warning("dataforseo: no task id in task_post response")
            return []
        payload = _poll_task(http, task_id, auth)
        if payload is None:
            logger.info("dataforseo: task not ready within poll timeout")
            return []
        return _candidates_from_result(payload)


def _redact_secrets(text: str) -> str:
    """Mask provider credentials if they ever appear in a response body/log."""
    out = text or ""
    for secret in (settings.DATAFORSEO_LOGIN, settings.DATAFORSEO_PASSWORD, settings.SERPER_API_KEY):
        if secret:
            out = out.replace(secret, "***")
    return out


def _extract_task_id(resp_json: dict) -> Optional[str]:
    for task in (resp_json.get("tasks") or []):
        tid = task.get("id")
        if tid:
            return str(tid)
    return None


def _poll_task(http: httpx.Client, task_id: str, auth) -> Optional[dict]:
    """Poll task_get/advanced until the task is ready, or the poll timeout elapses."""
    deadline = time.time() + settings.GMAIL_SEARCH_POLL_TIMEOUT
    url = f"{_API_BASE}/task_get/advanced/{task_id}"
    while time.time() < deadline:
        resp = http.get(url, auth=auth)
        if resp.status_code == 200:
            data = resp.json()
            for task in (data.get("tasks") or []):
                # 20000 = ok; result populated. 40602 = "task in queue" -> keep polling.
                status = task.get("status_code")
                if status == 20000 and task.get("result"):
                    return data
        time.sleep(settings.GMAIL_SEARCH_POLL_INTERVAL)
    return None
