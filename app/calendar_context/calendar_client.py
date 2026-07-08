"""Live Google Calendar reads — today's events for a connected user.

PRIVACY: nothing here is persisted. Events are fetched per request, used to build
ephemeral per-turn stylist context / the Home tile, then discarded. Only OAuth
tokens are stored (calendar_accounts); event titles/locations never touch our DB.

Fail-soft: any error (token expired past refresh, API error, malformed payload)
returns an empty list — a calendar outage never breaks a chat turn or the tile.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.calendar_context.calendar_oauth_service import get_calendar_client
from app.core.config import settings
from app.models import CalendarAccount

logger = logging.getLogger(__name__)


@dataclass
class CalendarEvent:
    """One event on the user's day. In-memory only — never persisted."""

    summary: str            # event title (live, ephemeral)
    start: datetime
    end: Optional[datetime]
    location: Optional[str]
    all_day: bool

    def start_label(self) -> str:
        """Compact clock label ('10:00', or 'all day')."""
        if self.all_day:
            return "all day"
        return self.start.strftime("%H:%M")

    def day_label(self) -> str:
        """Weekday + date the event falls on, UTC ('Mon Jul 8'). Used by the
        multi-day stylist context so the model can resolve 'today'/'tomorrow'/
        named days to the right events instead of guessing."""
        return f"{self.start:%a %b} {self.start.day}"


def _parse_dt(node: dict) -> tuple[Optional[datetime], bool]:
    """Parse a Google Calendar start/end node into (datetime, all_day)."""
    if not isinstance(node, dict):
        return None, False
    if node.get("dateTime"):
        raw = node["dateTime"].replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(raw), False
        except ValueError:
            return None, False
    if node.get("date"):  # all-day event
        try:
            d = datetime.fromisoformat(node["date"])
            return d.replace(tzinfo=timezone.utc), True
        except ValueError:
            return None, True
    return None, False


def fetch_events(
    account: CalendarAccount, db: Session, *, days_ahead: int = 0
) -> List[CalendarEvent]:
    """Upcoming events from now .. end of (today + ``days_ahead``), UTC, or [] on
    any failure. ``days_ahead=0`` is today-only (the Home tile); the stylist
    passes CALENDAR_CONTEXT_DAYS for a rolling multi-day window.

    Same privacy rule as today-only: a LIVE per-request read, nothing persisted.
    The per-day event cap scales with the window (CALENDAR_MAX_EVENTS per day) so
    a busy today can't crowd out tomorrow's events. PRIMARY calendar only.
    """
    if not settings.CALENDAR_ENABLED:
        return []
    days_ahead = max(0, days_ahead)
    try:
        service = get_calendar_client(account, db)
        now = datetime.now(timezone.utc)
        end_date = now.date() + timedelta(days=days_ahead)
        window_end = datetime.combine(end_date, time.max, tzinfo=timezone.utc)
        resp = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=window_end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=settings.CALENDAR_MAX_EVENTS * (days_ahead + 1),
            )
            .execute()
        )
    except Exception as exc:  # noqa: BLE001 — live read, fail soft
        logger.warning("Calendar fetch failed for user %s: %s", account.user_id, type(exc).__name__)
        return []

    events: List[CalendarEvent] = []
    for item in resp.get("items", []):
        start, all_day = _parse_dt(item.get("start", {}))
        if start is None:
            continue
        end, _ = _parse_dt(item.get("end", {}))
        events.append(
            CalendarEvent(
                summary=str(item.get("summary") or "(busy)"),
                start=start,
                end=end,
                location=(str(item["location"]) if item.get("location") else None),
                all_day=all_day,
            )
        )
    return events


def fetch_today_events(account: CalendarAccount, db: Session) -> List[CalendarEvent]:
    """Today's upcoming events (now .. end of day, UTC). Thin today-only wrapper
    over :func:`fetch_events` — the Home tile (GET /calendar/today) stays exactly
    as before, capped at CALENDAR_MAX_EVENTS."""
    return fetch_events(account, db, days_ahead=0)
