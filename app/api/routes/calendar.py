"""GET /calendar/today — the authenticated user's upcoming events for today,
read LIVE (never persisted). Powers the Home bento tile.

Fail-soft: not connected / provider down / disabled all return 200 with
``connected: false`` (or an empty list) so the tile degrades quietly. Event
titles are returned to the user's OWN client only and are never stored server-side.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.calendar_context import fetch_today_events
from app.core.config import settings
from app.dependencies import get_current_user, get_db
from app.models import CalendarAccount, User

router = APIRouter(tags=["calendar"])


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

    account = (
        db.query(CalendarAccount)
        .filter(CalendarAccount.user_id == current_user.id)
        .one_or_none()
    )
    if account is None or not account.refresh_token:
        return CalendarTodayResponse(connected=False)

    events = fetch_today_events(account, db)
    return CalendarTodayResponse(
        connected=True,
        events=[
            CalendarEventOut(summary=e.summary, start=e.start_label(), location=e.location)
            for e in events
        ],
    )
