"""Wrap resolver (Wave F1c): product URL + click_id -> affiliate (or plain) URL.

Fallback chain, first match wins:
  1. DIRECT program deep-link (SHEIN / AliExpress) — if that program's affiliate id is
     configured and direct deep-links are enabled.
  2. SOVRN (VigLink) wrap — if SOVRN_SITE_ID is set; click_id rides as the CUID subid.
  3. SKIMLINKS wrap — if SKIMLINKS_PUBLISHER_ID is set; click_id rides as the sub-ref.
  4. PLAIN redirect — return the destination unchanged (today's default when nothing is
     approved).

ONLY the destination URL + the opaque click_id are ever placed on the outbound wrapped
URL — never a user id, email, or closet datum. The click_id is our own opaque uuid used
solely to reconcile network postbacks (affiliate_conversions).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote, urlparse

from . import config


@dataclass
class WrapResult:
    url: str
    network: Optional[str]      # 'shein' | 'aliexpress' | 'sovrn' | 'skimlinks' | None
    wrapped: bool


def _registrable_domain(url: str) -> str:
    """Last two labels of the host (best-effort; enough for program matching)."""
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
    except Exception:
        return ""
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _direct_deeplink(dest_url: str, click_id: str) -> Optional[WrapResult]:
    """Per-program deep-link. Returns None unless the program id is configured."""
    if not config.direct_deeplinks_enabled():
        return None
    domain = _registrable_domain(dest_url)
    aff = config.program_affiliate_ids().get(domain)
    if not aff:
        return None
    enc = quote(dest_url, safe="")
    if domain == "shein.com":
        # SHEIN/CJ-style deep link: affiliate id + our click_id as sub id + target url.
        url = f"https://api.shein.com/deeplink?aff={aff}&subid={click_id}&url={enc}"
        return WrapResult(url=url, network="shein", wrapped=True)
    if domain == "aliexpress.com":
        url = f"https://s.click.aliexpress.com/deep_link.htm?aff_short_key={aff}&sub_id={click_id}&dl_target_url={enc}"
        return WrapResult(url=url, network="aliexpress", wrapped=True)
    return None


def _sovrn(dest_url: str, click_id: str) -> Optional[WrapResult]:
    site = config.sovrn_site_id()
    if not site:
        return None
    enc = quote(dest_url, safe="")
    # VigLink/Sovrn redirect; cuid carries OUR opaque click_id for postback matching.
    url = f"https://redirect.viglink.com/?key={site}&u={enc}&cuid={quote(click_id, safe='')}"
    return WrapResult(url=url, network="sovrn", wrapped=True)


def _skimlinks(dest_url: str, click_id: str) -> Optional[WrapResult]:
    pub = config.skimlinks_publisher_id()
    if not pub:
        return None
    enc = quote(dest_url, safe="")
    url = f"https://go.skimresources.com/?id={pub}&xs=1&url={enc}&sref={quote(click_id, safe='')}"
    return WrapResult(url=url, network="skimlinks", wrapped=True)


def wrap_url(dest_url: str, click_id: str) -> WrapResult:
    """Resolve the outbound URL for a click. Falls back to plain when nothing approved.

    dest_url is the product's own canonical/product URL (looked up server-side by
    click_id — never client-supplied). click_id is our opaque uuid.
    """
    for tier in (_direct_deeplink, _sovrn, _skimlinks):
        result = tier(dest_url, click_id)
        if result is not None:
            return result
    return WrapResult(url=dest_url, network=None, wrapped=False)
