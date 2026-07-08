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
from dataclasses import dataclass, field
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.calendar_context import CalendarEvent, fetch_today_events
from app.core.config import settings
from app.db import SessionLocal
from app.models import CalendarAccount

logger = logging.getLogger(__name__)


@dataclass
class DressContext:
    """Dress-code hints derived from today's events (in-memory only)."""

    occasion: Optional[str] = None
    formality_target: Optional[int] = None  # 1 casual .. 5 formal


@dataclass
class CalendarBlock:
    """The assembled calendar context a turn runs with. Titles are ephemeral."""

    connected: bool = False
    events: List[CalendarEvent] = field(default_factory=list)
    occasion: Optional[str] = None
    formality_target: Optional[int] = None

    @property
    def available(self) -> bool:
        return self.connected and bool(self.events)

    def to_prompt_text(self) -> str:
        """Compact schedule line for the system prompt (never persisted)."""
        if not self.available:
            return ""
        parts = []
        for ev in self.events:
            loc = f" ({ev.location})" if ev.location else ""
            parts.append(f"{ev.start_label()} {ev.summary}{loc}")
        line = "Today's calendar: " + "; ".join(parts) + "."
        if self.formality_target is not None:
            line += (
                f" Dress for the dressiest thing on it"
                f"{f' — {self.occasion}' if self.occasion else ''} "
                f"(formality ~{self.formality_target}/5). Weigh it, don't obey it blindly."
            )
        return line


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
    db: Session, user_id: UUID, *, no_persist: bool = False
) -> CalendarBlock:
    """Build the per-turn calendar block, or an empty one when unavailable.

    ``no_persist`` (incognito) short-circuits to empty BEFORE any token read or
    network call — a private turn reads no calendar at all.
    """
    if no_persist or not settings.CALENDAR_ENABLED:
        return CalendarBlock()

    # (1) RLS-scoped connectivity read — enabled by the 0027 GRANT.
    account = (
        db.query(CalendarAccount)
        .filter(CalendarAccount.user_id == user_id)
        .one_or_none()
    )
    if account is None or not account.refresh_token:
        return CalendarBlock()

    # (2) Live fetch on an OWN owner session (token refresh commits there).
    events = _fetch_live_events(user_id)
    if not events:
        return CalendarBlock(connected=True)

    derived = derive_dress_context(events)
    return CalendarBlock(
        connected=True,
        events=events,
        occasion=derived.occasion,
        formality_target=derived.formality_target,
    )


def _fetch_live_events(user_id: UUID) -> List[CalendarEvent]:
    """Fetch today's events on a dedicated owner session (isolated from the turn
    transaction so the token-refresh commit is safe). Fail-soft to []."""
    session = SessionLocal()
    try:
        account = (
            session.query(CalendarAccount)
            .filter(CalendarAccount.user_id == user_id)
            .one_or_none()
        )
        if account is None:
            return []
        return fetch_today_events(account, session)
    except Exception as exc:  # noqa: BLE001 — never break the turn on calendar
        logger.warning("Calendar live fetch failed: %s", type(exc).__name__)
        return []
    finally:
        session.close()
