"""Shared abuse controls for the chat endpoint (Wave S2 scope D).

WHY POSTGRES, NOT REDIS: the deployment has no Redis, and the locked decision
demands SHARED (cross-worker) + durable state. Postgres is the one store every
uvicorn worker already shares, and the volumes here are tiny (one limiter row
per user, one usage row per user per day), so it is the right fallback:

  * RATE LIMIT   — fixed 60-second window in ``chat_rate_windows`` (one row per
    user), advanced with a single atomic ``INSERT ... ON CONFLICT DO UPDATE ...
    RETURNING count``. Atomic upsert = correct under concurrent workers. The
    same SQL shape runs on SQLite (dev/tests) since 3.24.
  * DAILY QUOTA  — read the caller's ``chat_usage`` row for the current UTC day
    (turns + dollars); exceeded -> 429 before any model call spends money.
    Usage is recorded via the same atomic-upsert pattern after the turn.
  * CONCURRENCY  — per-user in-flight SSE turns, capped with Postgres SESSION
    advisory locks: slot k of N is ``pg_try_advisory_lock(CLASS_ID,
    hash(user_id, k))`` on a DEDICATED connection held for the stream's life.
    Advisory locks are released automatically when the connection dies, so a
    crashed worker can never leak a slot (self-healing, unlike a counter).
    SQLite fallback: an in-process per-user counter (single-process dev only).
"""
from __future__ import annotations

import hashlib
import logging
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Dict, Iterator, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.usage_windows import today_local
from app.db import engine
from app.models import ChatUsage

logger = logging.getLogger(__name__)

# Namespace for this app's advisory locks (int32). Stable, arbitrary.
_ADVISORY_CLASS_ID = 0x7A11  # 'TAIL'-ish; 31249

_RATE_WINDOW_SECONDS = 60


class ChatLimitExceeded(Exception):
    """Base for 429-worthy refusals. ``retry_after`` is advisory seconds."""

    def __init__(self, message: str, *, code: str, retry_after: Optional[int] = None):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


class RateLimited(ChatLimitExceeded):
    def __init__(self, retry_after: int):
        super().__init__(
            "Too many messages — give it a few seconds.",
            code="rate_limited", retry_after=retry_after,
        )


class QuotaExceeded(ChatLimitExceeded):
    def __init__(self) -> None:
        super().__init__(
            "You've reached today's free stylist limit. It resets at the start of "
            "your next day.",
            code="quota_exceeded",
        )


class TooManyStreams(ChatLimitExceeded):
    def __init__(self) -> None:
        super().__init__(
            "A styling reply is already in progress — wait for it to finish.",
            code="concurrent_limit", retry_after=5,
        )


# ---------------------------------------------------------------------------
# Rate limit (fixed window, atomic upsert — cross-worker correct)
# ---------------------------------------------------------------------------
_RATE_SQL = text(
    """
    INSERT INTO chat_rate_windows (user_id, window_start, count)
    VALUES (:user_id, :now, 1)
    ON CONFLICT (user_id) DO UPDATE SET
        count = CASE WHEN chat_rate_windows.window_start < :cutoff
                     THEN 1 ELSE chat_rate_windows.count + 1 END,
        window_start = CASE WHEN chat_rate_windows.window_start < :cutoff
                            THEN :now ELSE chat_rate_windows.window_start END
    RETURNING count
    """
)


def check_rate_limit(db: Session, user_id: UUID) -> None:
    """Count this request against the caller's 60s window; raise when over."""
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=_RATE_WINDOW_SECONDS)
    params = {"user_id": _uid_param(db, user_id), "now": now, "cutoff": cutoff}
    count = db.execute(_RATE_SQL, params).scalar_one()
    db.commit()
    if int(count) > settings.CHAT_RATE_LIMIT_PER_MINUTE:
        raise RateLimited(retry_after=_RATE_WINDOW_SECONDS)


def _uid_param(db: Session, user_id: UUID):
    """UUID params bind natively on Postgres; the SQLite GUID column stores text."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        return user_id
    return str(user_id)


# ---------------------------------------------------------------------------
# Daily quota (turns + dollars, UTC day)
# ---------------------------------------------------------------------------
def check_quota(db: Session, user_id: UUID, *, tz_name: Optional[str] = None) -> None:
    """Raise QuotaExceeded when the caller is at/over today's turn or cost cap.

    The "day" boundary honours the user's tz (facts.location.timezone) when provided,
    else UTC — the same rule the calendar/photo-quota paths use (app.core.usage_windows).
    check_quota and record_turn_usage MUST be passed the same tz_name so a turn is read
    and written under the same day row."""
    today = today_local(tz_name)
    row = (
        db.query(ChatUsage)
        .filter(ChatUsage.user_id == user_id, ChatUsage.period_start == today)
        .one_or_none()
    )
    if row is None:
        return
    if int(row.turns or 0) >= settings.CHAT_DAILY_TURN_QUOTA:
        raise QuotaExceeded()
    if float(row.cost_usd or 0) >= settings.CHAT_DAILY_COST_QUOTA_USD:
        raise QuotaExceeded()


def record_turn_usage(
    db: Session,
    user_id: UUID,
    *,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    tz_name: Optional[str] = None,
) -> None:
    """Atomically roll this turn into today's chat_usage row. Best-effort —
    a bookkeeping failure must never break a delivered reply (usage.py pattern).

    ``tz_name`` picks the day row (user-local, else UTC) and MUST match the value
    check_quota was called with, so a recorded turn counts against the same day it is
    later checked against."""
    today: date = today_local(tz_name)
    sql = text(
        """
        INSERT INTO chat_usage
            (id, user_id, period_start, turns, input_tokens, output_tokens,
             cost_usd, updated_at)
        VALUES (:id, :user_id, :today, 1, :it, :ot, :cost, :now)
        ON CONFLICT (user_id, period_start) DO UPDATE SET
            turns = chat_usage.turns + 1,
            input_tokens = chat_usage.input_tokens + :it,
            output_tokens = chat_usage.output_tokens + :ot,
            cost_usd = chat_usage.cost_usd + :cost,
            updated_at = :now
        """
    )
    import uuid as _uuid

    try:
        new_id = _uuid.uuid4()
        db.execute(
            sql,
            {
                "id": _uid_param(db, new_id),
                "user_id": _uid_param(db, user_id),
                "today": today,
                "it": int(input_tokens or 0),
                "ot": int(output_tokens or 0),
                "cost": float(cost_usd or 0.0),
                "now": datetime.utcnow(),
            },
        )
        db.commit()
    except Exception as exc:
        logger.warning("record_turn_usage failed: %s", type(exc).__name__)
        try:
            db.rollback()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Concurrency cap (Postgres advisory locks; in-process fallback on SQLite)
# ---------------------------------------------------------------------------
_local_lock = threading.Lock()
_local_streams: Dict[str, int] = {}


def _slot_key(user_id: UUID, slot: int) -> int:
    """Deterministic int32 for (user, slot) — the advisory lock's objid."""
    digest = hashlib.sha256(f"{user_id}:{slot}".encode()).digest()
    return int.from_bytes(digest[:4], "big", signed=True)


@contextmanager
def stream_slot(user_id: UUID) -> Iterator[None]:
    """Hold one of the user's CHAT_MAX_CONCURRENT_STREAMS slots for the stream's
    lifetime. Raises TooManyStreams when all slots are busy."""
    if engine.dialect.name == "postgresql":
        # Dedicated connection: session-level advisory locks live and die with it.
        connection = engine.connect()
        acquired_slot: Optional[int] = None
        try:
            for slot in range(settings.CHAT_MAX_CONCURRENT_STREAMS):
                got = connection.execute(
                    text("SELECT pg_try_advisory_lock(:cls, :obj)"),
                    {"cls": _ADVISORY_CLASS_ID, "obj": _slot_key(user_id, slot)},
                ).scalar_one()
                if got:
                    acquired_slot = slot
                    break
            if acquired_slot is None:
                raise TooManyStreams()
            yield
        finally:
            if acquired_slot is not None:
                try:
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:cls, :obj)"),
                        {"cls": _ADVISORY_CLASS_ID,
                         "obj": _slot_key(user_id, acquired_slot)},
                    )
                except Exception:
                    pass  # connection close releases session locks anyway
            connection.close()
        return

    # SQLite dev/test fallback: per-process counter (documented limitation).
    key = str(user_id)
    with _local_lock:
        if _local_streams.get(key, 0) >= settings.CHAT_MAX_CONCURRENT_STREAMS:
            raise TooManyStreams()
        _local_streams[key] = _local_streams.get(key, 0) + 1
    try:
        yield
    finally:
        with _local_lock:
            _local_streams[key] = max(0, _local_streams.get(key, 0) - 1)
            if _local_streams[key] == 0:
                _local_streams.pop(key, None)
