"""Raw HTML extraction + DOM association + og:image parsing (P3.7 split of the
image_resolver god-module).

Pure parsing/scoring concern: no network, no storage, no tier logic. Maps the
receipt email's <img>/<a> elements to line items by proximity (``associate``),
and separately reads a product page's <head> for its og:image (``extract_og_image``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.gmail_closet.fetch_service import _decode_b64

if TYPE_CHECKING:
    # Deferred to avoid a circular import: resolve.py imports associate/extract_og_image
    # from this module, so this module must not import ResolverItem from resolve.py at
    # runtime. Type-checking only; associate()/_score() duck-type on item.name/.color/
    # .unit_price and never isinstance-check, so this has zero runtime effect.
    from app.gmail_closet.image_resolver.resolve import ResolverItem

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


@dataclass
class _ImgCand:
    kind: str            # 'cid' | 'remote'
    ref: str             # content-id (cid) or absolute https url (remote)
    alt: str
    context: str          # text of the nearest block ancestor
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


def _score(item: "ResolverItem", cand: _ImgCand) -> int:
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


def associate(html: str, items: "List[ResolverItem]") -> List[_ItemRefs]:
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
