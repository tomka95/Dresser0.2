"""Calendar READ path for the stylist (sibling to profile.py).

Assembles the per-turn calendar block the agent's system prompt carries and the
compose_outfit tool derives dress-context from. Two-session dance, on purpose:

  1. The "is this user connected?" read runs on the caller's RLS-SCOPED session
     (the agent turn's connection, role ``authenticated``). That read is exactly
     what the explicit GRANT in migration 0027 enables — it proves the RLS-scoped
     role can reach calendar_accounts.
  2. The LIVE event fetch refreshes the access token, which COMMITS, so it must
     run on its own owner ``SessionLocal`` — committing the agent's transaction
     mid-turn would drop the SET LOCAL role/claims for the rest of the turn.

PRIVACY: event titles are read live and used to build an EPHEMERAL prompt block +
derive a dress context. Nothing is persisted. INCOGNITO turns (no_persist) skip
calendar entirely — no token read, no network call, zero trace.
"""
from __future__ import annotations

import logging
import threading
import time as _time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.calendar_context import CalendarEvent, fetch_events
from app.core.config import settings
from app.db import SessionLocal
from app.models import CalendarAccount

logger = logging.getLogger(__name__)

try:  # stdlib since 3.9; fall back to UTC-only bucketing if unavailable
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _tzinfo(tz_name: Optional[str]):
    """The user's tz, or UTC when unknown/unparseable — the fallback everything
    here shares so a missing facts.location.timezone degrades to UTC, never errors."""
    if tz_name and ZoneInfo is not None:
        try:
            return ZoneInfo(tz_name)
        except Exception:  # unknown tz name -> UTC
            return timezone.utc
    return timezone.utc


def _tz_from_facts(facts: Optional[Dict]) -> Optional[str]:
    """IANA tz name from style_profiles.facts.location.timezone (same field the
    weather path reads), or None → UTC fallback."""
    loc = (facts or {}).get("location")
    if isinstance(loc, dict):
        tz = loc.get("timezone")
        if isinstance(tz, str) and tz.strip():
            return tz
    return None


def _today_local(tz_name: Optional[str]) -> date:
    return datetime.now(timezone.utc).astimezone(_tzinfo(tz_name)).date()


def _event_local_date(ev: CalendarEvent, tz_name: Optional[str]) -> date:
    """The calendar date an event falls on in the user's tz. All-day events carry
    a bare date (midnight UTC) — bucket them by that literal date, never shifted
    by a tz conversion; timed events convert from UTC to local."""
    if ev.all_day:
        return ev.start.date()
    return ev.start.astimezone(_tzinfo(tz_name)).date()


def resolve_target_date(
    token: Optional[str], *, today: Optional[date] = None, tz_name: Optional[str] = None
) -> Optional[date]:
    """Map a model-supplied day token to a concrete date in the user's tz, or None
    if it can't be resolved (→ caller defaults to today). Accepts an ISO date
    (YYYY-MM-DD), 'today'/'tomorrow', or a weekday name (next occurrence on/after
    today). ``today`` overrides the reference day (tests); otherwise it is the
    current local day in ``tz_name`` (UTC when absent)."""
    if not token:
        return None
    today = today or _today_local(tz_name)
    t = token.strip().lower()
    if t in ("today", "tonight"):
        return today
    if t == "tomorrow":
        return today + timedelta(days=1)
    try:
        return date.fromisoformat(t)
    except ValueError:
        pass
    if t in _WEEKDAYS:
        target_wd = _WEEKDAYS.index(t)
        delta = (target_wd - today.weekday()) % 7  # next occurrence, today if same
        return today + timedelta(days=delta)
    return None


@dataclass
class DressContext:
    """Dress-code hints derived from today's events (in-memory only)."""

    occasion: Optional[str] = None
    formality_target: Optional[int] = None  # 1 casual .. 5 formal


@dataclass
class CalendarBlock:
    """The assembled calendar context a turn runs with. Titles are ephemeral.

    ``events`` spans a rolling multi-day window (today .. +CALENDAR_CONTEXT_DAYS).
    ``occasion``/``formality_target`` are TODAY's derived dress context — the
    default compose_outfit falls back to when the request doesn't target a
    specific day. Per-day derivation is available via :meth:`dress_context_for`.
    ``tz_name`` is the user's IANA timezone (facts.location.timezone); all
    day-bucketing / today-tomorrow labels / target_day resolution happen in it,
    falling back to UTC when absent.
    """

    connected: bool = False
    events: List[CalendarEvent] = field(default_factory=list)
    occasion: Optional[str] = None
    formality_target: Optional[int] = None
    tz_name: Optional[str] = None

    @property
    def available(self) -> bool:
        return self.connected and bool(self.events)

    def events_on(self, day: date) -> List[CalendarEvent]:
        """Events that fall on ``day`` in the user's local timezone."""
        return [ev for ev in self.events if _event_local_date(ev, self.tz_name) == day]

    def dress_context_for(self, target_day: Optional[str]) -> "DressContext":
        """Derive occasion/formality for the day the request targets. Ambiguous or
        unresolvable → TODAY's context. A resolvable day with no events → empty
        (so a free day doesn't inherit today's occasion)."""
        target = resolve_target_date(target_day, tz_name=self.tz_name)
        if target is None:
            return DressContext(occasion=self.occasion, formality_target=self.formality_target)
        return derive_dress_context(self.events_on(target))

    def to_prompt_text(self) -> str:
        """Multi-day, date-labeled schedule for the system prompt (never persisted).

        Each day is tagged with its weekday + date (and today/tomorrow) in the
        user's local timezone, so the model resolves 'today'/'tomorrow'/named days
        to the right events instead of misattributing today's events to another
        day. Clock times are shown local too, to match the day headers."""
        if not self.available:
            return ""
        tz_name = self.tz_name
        tz = _tzinfo(tz_name)
        today = _today_local(tz_name)
        tomorrow = today + timedelta(days=1)
        by_day: Dict[date, List[CalendarEvent]] = {}
        for ev in self.events:
            by_day.setdefault(_event_local_date(ev, tz_name), []).append(ev)

        def _clock(ev: CalendarEvent) -> str:
            return "all day" if ev.all_day else ev.start.astimezone(tz).strftime("%H:%M")

        lines: List[str] = []
        for day in sorted(by_day):
            rel = " (today)" if day == today else " (tomorrow)" if day == tomorrow else ""
            label = f"{day:%a %b} {day.day}{rel}"
            evs = "; ".join(
                f"{_clock(ev)} {ev.summary}{f' ({ev.location})' if ev.location else ''}"
                for ev in by_day[day]
            )
            lines.append(f"- {label}: {evs}.")

        block = "Upcoming calendar (live, next few days — titles are private, never stored):\n"
        block += "\n".join(lines)
        if self.formality_target is not None:
            block += (
                f"\nFor TODAY, dress for the dressiest thing"
                f"{f' — {self.occasion}' if self.occasion else ''} "
                f"(formality ~{self.formality_target}/5). Weigh it, don't obey it blindly."
            )
        block += (
            "\nWhen the user asks about a specific day (tomorrow, a named weekday), "
            "read THAT day's events above and pass compose_outfit's target_day so "
            "the occasion is derived from the right day — never assume today's."
        )
        return block


# Keyword -> (occasion, formality). Highest formality across the day wins ("dress
# for the dressiest thing"). Word-level, case-insensitive, substring-tolerant.
_DRESS_RULES = (
    (("black tie", "black-tie", "gala", "wedding", "ceremony", "formal"), "a formal event", 5),
    (("interview",), "an interview", 4),
    (("client", "board", "presentation", "pitch", "conference", "review",
      "meeting", "office", "work", "1:1", "standup", "sync"), "work", 4),
    (("dinner", "date night", "cocktail", "drinks", "party", "reception"), "dinner out", 4),
    (("brunch", "lunch", "coffee", "casual"), "something casual", 2),
    (("gym", "workout", "training", "yoga", "pilates", "run", "spin"), "the gym", 1),
)


def derive_dress_context(events: List[CalendarEvent]) -> DressContext:
    """Map today's event text to an occasion + formality target. Pure."""
    best: DressContext = DressContext()
    best_rank = -1
    for ev in events:
        hay = f"{ev.summary} {ev.location or ''}".lower()
        for keywords, occasion, formality in _DRESS_RULES:
            if any(k in hay for k in keywords):
                if formality > best_rank:
                    best_rank = formality
                    best = DressContext(occasion=occasion, formality_target=formality)
                break  # first matching rule per event
    return best


def assemble_calendar(
    db: Session,
    user_id: UUID,
    *,
    no_persist: bool = False,
    facts: Optional[Dict] = None,
) -> CalendarBlock:
    """Build the per-turn calendar block, or an empty one when unavailable.

    ``facts`` (style_profiles.facts) supplies the user's timezone via
    ``facts.location.timezone`` — the same field the weather path reads — so
    day-bucketing / today-tomorrow labels / target_day all resolve in local
    time. Absent → UTC. ``no_persist`` (incognito) short-circuits to empty BEFORE
    any token read or network call — a private turn reads no calendar at all.
    """
    if no_persist or not settings.CALENDAR_ENABLED:
        return CalendarBlock()

    tz_name = _tz_from_facts(facts)

    # (1) RLS-scoped connectivity read — enabled by the 0027 GRANT.
    account = (
        db.query(CalendarAccount)
        .filter(CalendarAccount.user_id == user_id)
        .one_or_none()
    )
    if account is None or not account.refresh_token:
        return CalendarBlock(tz_name=tz_name)

    # (2) Live fetch on an OWN owner session (token refresh commits there). The
    #     window spans today..+CALENDAR_CONTEXT_DAYS so "what about tomorrow?" sees
    #     the right day; occasion/formality default to TODAY's events (per-day
    #     derivation happens in compose_outfit when a request targets another day).
    events = _fetch_live_events(user_id, days_ahead=settings.CALENDAR_CONTEXT_DAYS)
    if not events:
        return CalendarBlock(connected=True, tz_name=tz_name)

    today = _today_local(tz_name)
    derived = derive_dress_context(
        [ev for ev in events if _event_local_date(ev, tz_name) == today]
    )
    return CalendarBlock(
        connected=True,
        events=events,
        occasion=derived.occasion,
        formality_target=derived.formality_target,
        tz_name=tz_name,
    )


# Short-lived, per-(user, window) IN-PROCESS cache for the stylist's live window
# fetch — the calendar analogue of the Home tile's cache, but re-keyed to the
# WINDOW so a multi-day fetch is never served where a today-only one is expected
# (and vice-versa). EPHEMERAL process memory only: no DB, no titles persisted;
# incognito turns short-circuit before this is ever consulted. Keyed by
# (user_id, days_ahead).
_events_cache: Dict[Tuple[UUID, int], Tuple[float, List[CalendarEvent]]] = {}
_events_cache_lock = threading.Lock()


def _cached_events(user_id: UUID, days_ahead: int) -> Optional[List[CalendarEvent]]:
    with _events_cache_lock:
        entry = _events_cache.get((user_id, days_ahead))
    if entry is None:
        return None
    ts, value = entry
    if _time.monotonic() - ts > settings.CALENDAR_TODAY_CACHE_TTL_SECONDS:
        return None
    return value


def _cache_events(user_id: UUID, days_ahead: int, value: List[CalendarEvent]) -> None:
    with _events_cache_lock:
        _events_cache[(user_id, days_ahead)] = (_time.monotonic(), value)


def _fetch_live_events(user_id: UUID, *, days_ahead: int = 0) -> List[CalendarEvent]:
    """Fetch the event window on a dedicated owner session (isolated from the turn
    transaction so the token-refresh commit is safe). Fail-soft to []. Served from
    a short per-(user, window) cache when warm."""
    cached = _cached_events(user_id, days_ahead)
    if cached is not None:
        return cached
    session = SessionLocal()
    try:
        account = (
            session.query(CalendarAccount)
            .filter(CalendarAccount.user_id == user_id)
            .one_or_none()
        )
        if account is None:
            return []
        events = fetch_events(account, session, days_ahead=days_ahead)
        _cache_events(user_id, days_ahead, events)
        return events
    except Exception as exc:  # noqa: BLE001 — never break the turn on calendar
        logger.warning("Calendar live fetch failed: %s", type(exc).__name__)
        return []
    finally:
        session.close()
