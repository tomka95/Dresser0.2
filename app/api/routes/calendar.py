"""GET /calendar/today — the authenticated user's upcoming events for today,
read LIVE (never persisted). Powers the Home bento tile.

Fail-soft: not connected / provider down / disabled all return 200 with
``connected: false`` (or an empty list) so the tile degrades quietly. Event
titles are returned to the user's OWN client only and are never stored server-side.
"""
from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.calendar_context import fetch_today_events
from app.core.config import settings
from app.dependencies import get_current_user, get_db
from app.models import CalendarAccount, User

router = APIRouter(tags=["calendar"])

# EPHEMERAL, in-process, per-user cache for today's events. Purely a fetch-lag
# fix so rapid Home re-mounts don't re-hit Google every time. Lives in memory for
# one worker process; NOT persisted to the DB, NOT shared across workers, gone on
# restart — the "no event titles in the DB" rule is unaffected (this is the same
# process memory the live response already passes through). Keyed by user id.
_today_cache: Dict[UUID, Tuple[float, "CalendarTodayResponse"]] = {}
_today_cache_lock = threading.Lock()


def _cache_get(user_id: UUID) -> Optional["CalendarTodayResponse"]:
    with _today_cache_lock:
        entry = _today_cache.get(user_id)
    if entry is None:
        return None
    ts, value = entry
    if time.monotonic() - ts > settings.CALENDAR_TODAY_CACHE_TTL_SECONDS:
        return None
    return value


def _cache_put(user_id: UUID, value: "CalendarTodayResponse") -> None:
    with _today_cache_lock:
        _today_cache[user_id] = (time.monotonic(), value)


class CalendarEventOut(BaseModel):
    summary: str
    start: str          # HH:MM or 'all day'
    location: Optional[str] = None


class CalendarTodayResponse(BaseModel):
    connected: bool
    events: List[CalendarEventOut] = []


@router.get("/calendar/today", response_model=CalendarTodayResponse)
def calendar_today(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CalendarTodayResponse:
    if not settings.CALENDAR_ENABLED:
        return CalendarTodayResponse(connected=False)

    # Serve a fresh in-process cache hit without touching the DB or Google.
    cached = _cache_get(current_user.id)
    if cached is not None:
        return cached

    account = (
        db.query(CalendarAccount)
        .filter(CalendarAccount.user_id == current_user.id)
        .one_or_none()
    )
    if account is None or not account.refresh_token:
        # Not connected is cheap (no Google call) — don't cache it, so a fresh
        # connect is reflected on the next mount.
        return CalendarTodayResponse(connected=False)

    events = fetch_today_events(account, db)
    result = CalendarTodayResponse(
        connected=True,
        events=[
            CalendarEventOut(summary=e.summary, start=e.start_label(), location=e.location)
            for e in events
        ],
    )
    _cache_put(current_user.id, result)  # ephemeral; TTL-bounded
    return result
