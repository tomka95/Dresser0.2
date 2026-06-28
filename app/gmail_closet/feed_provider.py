"""Pluggable product-feed seam (Tier 4.5 of the image waterfall) — Phase 4 stub.

WHERE THIS SITS
---------------
The image resolver's waterfall is:

    inline -> email-img -> CACHE -> og:image -> [FEED] -> search

A FEED provider maps a product identity (brand, name, color) to a FIRST-PARTY
product-image URL via an affiliate/commerce feed (Sovrn, Awin, a merchant catalog,
…). It sits between og:image (the email's own product link) and shopping search (the
paid long-tail fallback): often a clean catalog image is one feed lookup away, no
search query needed.

THE SEAM (what a real provider must implement)
----------------------------------------------
    FeedProvider.lookup(brand, name, color) -> FeedResult | None

``FeedResult.image_url`` is a URL ONLY — never image bytes. The resolver guard-fetches
that URL (SSRF-hardened), vision-verifies the bytes against the item, and only then
commits + seeds the shared cache. So a feed image is treated exactly like any other
untrusted web image: it CANNOT reach a card without passing verify. A real Sovrn/Awin
implementation therefore needs zero resolver changes — it just returns a URL.

SHIPPED STATE
-------------
``NullFeedProvider`` returns None for everything, and ``GMAIL_FEED_ENABLED`` defaults
False, so Tier 4.5 is a guaranteed no-op until a real provider is wired. Swap the
provider by replacing ``_provider`` / extending ``get_feed_provider`` — the resolver
calls ``get_feed_provider().lookup(...)`` and nothing else.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass
class FeedResult:
    """A product-feed hit. Carries a URL ONLY — never image bytes.

    image_url      : a first-party product-image URL (guard-fetched + verified later).
    source_domain  : the retailer/merchant domain, recorded as the cache row's
                     source_domain for provenance.
    detail         : short, redaction-safe note for reports (e.g. the feed name).
    """
    image_url: str
    source_domain: str = ""
    detail: str = ""


@runtime_checkable
class FeedProvider(Protocol):
    """A brand+name+color -> FeedResult|None lookup. Implementations MUST NOT fetch or
    return image bytes — only a URL the resolver will guard-fetch + verify."""

    def lookup(
        self, brand: Optional[str], name: Optional[str], color: Optional[str]
    ) -> Optional[FeedResult]:
        ...


class NullFeedProvider:
    """The shipped default: no feed configured -> every lookup misses (returns None).

    Keeps Tier 4.5 a safe no-op until a real provider plugs in. Never raises.
    """

    def lookup(
        self, brand: Optional[str], name: Optional[str], color: Optional[str]
    ) -> Optional[FeedResult]:
        return None


# Module-level singleton. A real provider (Sovrn/Awin/…) is wired by reassigning this
# in its own module's import side effect, or by extending get_feed_provider() to
# construct it from settings. Until then it is the Null provider.
_provider: FeedProvider = NullFeedProvider()


def get_feed_provider() -> FeedProvider:
    """Return the active FeedProvider (NullFeedProvider until a real one is wired).

    The resolver consults this ONLY when settings.GMAIL_FEED_ENABLED is true, so even
    a future real provider stays dark behind the flag.
    """
    return _provider
