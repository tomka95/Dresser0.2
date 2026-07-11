"""User-local time windows for usage quotas (SCRUM-44).

The boundary a quota resets on — the "month" for photo generations, the "day" for
chat messages — is computed in the USER'S timezone when
``style_profiles.facts.location.timezone`` is set, and falls back to UTC when it is
absent or unparseable. This is the EXACT rule the calendar read path uses
(``app/services/stylist/calendar.py`` — ``_tz_from_facts`` / ``_today_local``); it is
lifted here, pure and DB-free, so it can live in ``app.core`` (the leaf layer every
other layer may import) and be shared by both the photo-quota ledger
(``app.photo_closet.quota``) and the chat limiter (``app.services.stylist.limits``)
without either reaching across into the other.

Pure functions only: they take a ``facts`` dict or an IANA tz name and return
dates / aware datetimes. No SQLAlchemy, no models, no settings.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

_ONE_DAY = timedelta(days=1)

try:  # stdlib since 3.9; degrade to UTC-only bucketing if unavailable
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


def tzinfo_for(tz_name: Optional[str]):
    """The user's tz, or UTC when unknown/unparseable — the shared fallback so a
    missing facts.location.timezone degrades to UTC and never errors."""
    if tz_name and ZoneInfo is not None:
        try:
            return ZoneInfo(tz_name)
        except Exception:  # unknown tz name -> UTC
            return timezone.utc
    return timezone.utc


def tz_name_from_facts(facts: Optional[Dict[str, Any]]) -> Optional[str]:
    """IANA tz name from ``style_profiles.facts.location.timezone`` (the same field
    the calendar + weather paths read), or ``None`` → UTC fallback."""
    loc = (facts or {}).get("location")
    if isinstance(loc, dict):
        tz = loc.get("timezone")
        if isinstance(tz, str) and tz.strip():
            return tz
    return None


def today_local(tz_name: Optional[str]) -> date:
    """Today's calendar date in the user's tz (UTC when tz_name is None)."""
    return datetime.now(timezone.utc).astimezone(tzinfo_for(tz_name)).date()


def month_start_local(tz_name: Optional[str]) -> date:
    """First day of the current month in the user's tz — the photo-quota period key."""
    return today_local(tz_name).replace(day=1)


def day_reset_at(tz_name: Optional[str]) -> datetime:
    """Aware datetime of the next local midnight — when a per-day quota resets."""
    tz = tzinfo_for(tz_name)
    start_next = datetime.combine(today_local(tz_name), datetime.min.time()) + _ONE_DAY
    return start_next.replace(tzinfo=tz)


def month_reset_at(tz_name: Optional[str]) -> datetime:
    """Aware datetime of the first instant of next month in the user's tz — when a
    per-month quota resets."""
    tz = tzinfo_for(tz_name)
    first = month_start_local(tz_name)
    if first.month == 12:
        nxt = first.replace(year=first.year + 1, month=1)
    else:
        nxt = first.replace(month=first.month + 1)
    return datetime.combine(nxt, datetime.min.time()).replace(tzinfo=tz)
