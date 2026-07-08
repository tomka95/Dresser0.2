"""Google Calendar context source (calendar.events.readonly).

Connect plumbing + LIVE per-request event reads. NO calendar content is ever
persisted — only the OAuth tokens live in `calendar_accounts` (encrypted). Every
read (stylist per-turn context, Home tile) fetches events live and fails soft.

Public surface:
  * ``CalendarEvent`` / ``fetch_today_events`` — live events for a connected user.
  * ``ensure_fresh_token`` / ``get_calendar_client`` — token refresh + API client.
"""
from app.calendar_context.calendar_client import CalendarEvent, fetch_today_events
from app.calendar_context.calendar_oauth_service import (
    ensure_fresh_token,
    get_calendar_client,
)

__all__ = [
    "CalendarEvent",
    "fetch_today_events",
    "ensure_fresh_token",
    "get_calendar_client",
]
