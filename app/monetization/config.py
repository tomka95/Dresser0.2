"""Monetization config surface — env-backed account-id stubs (Wave F1c).

All account ids default to empty. With nothing configured, the wrap resolver returns the
plain product URL (today's approved default). Guy fills these via env as programs get
approved; no code change needed to switch a tier on.
"""
from __future__ import annotations

from typing import Optional

from app.core.config import settings


def _clean(v: Optional[str]) -> Optional[str]:
    v = (v or "").strip()
    return v or None


def sovrn_site_id() -> Optional[str]:
    return _clean(settings.SOVRN_SITE_ID)


def skimlinks_publisher_id() -> Optional[str]:
    return _clean(settings.SKIMLINKS_PUBLISHER_ID)


def direct_deeplinks_enabled() -> bool:
    return bool(settings.MONETIZATION_DIRECT_DEEPLINK_ENABLED)


def click_rate_limit_per_minute() -> int:
    return int(settings.CLICK_RATE_LIMIT_PER_MINUTE)


# Registrable-domain -> configured affiliate id for a DIRECT program deep-link.
# Empty today (stubs); a non-None value activates that program's deep-link tier.
def program_affiliate_ids() -> dict:
    return {
        "shein.com": _clean(settings.SHEIN_AFFILIATE_ID),
        "aliexpress.com": _clean(settings.ALIEXPRESS_AFFILIATE_ID),
    }
