"""Photo-quota ledger + enforcement (SCRUM-44).

The free tier is "30 photos a month" (``settings.PHOTO_MONTHLY_QUOTA``). This module
owns the monthly counter AND the entry-point enforcement:

  * ``check_photo_quota`` — the read the ingest-commit + regenerate routes call BEFORE
    starting work; raises ``PhotoQuotaExceeded`` (→ 429 ``{limit, used, resets_at}``)
    once the user is at/over their monthly cap.
  * ``record_photo_usage`` — the SUCCESS-ONLY increment. It is called from the
    generation orchestrators (``run_photo_generation`` stats.ready / the regenerate
    success branch) so a failed generate->verify never burns quota — only a garment
    that actually reaches a verified card counts.

Mirrors app/services/stylist/limits (the chat limiter): an atomic ON CONFLICT upsert on
the (user_id, period_start) unique key so the count stays correct across the web + worker
processes. ``period_start`` is the first day of the usage month in the USER'S timezone
when ``facts.location.timezone`` is set, else UTC — the same rule the calendar uses
(see app.core.usage_windows). Recording is best-effort — a bookkeeping failure must
never break the user-facing action it accompanies; enforcement (check_photo_quota) is
NOT best-effort (it raises to reject).
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import date, datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.usage_windows import month_reset_at, month_start_local
from app.models import PhotoUsage

logger = logging.getLogger(__name__)


class PhotoQuotaExceeded(Exception):
    """Raised by ``check_photo_quota`` when the caller is at/over their monthly cap.

    Carries the fields the 429 payload needs: ``limit`` (monthly cap), ``used``
    (successful generations this period), and ``resets_at`` (ISO-8601 instant the
    period rolls over, in the user's tz)."""

    def __init__(self, *, limit: int, used: int, resets_at: str):
        super().__init__("Monthly photo generation limit reached.")
        self.limit = limit
        self.used = used
        self.resets_at = resets_at


def month_start(d: date | None = None, tz_name: Optional[str] = None) -> date:
    """First day of the usage month. With ``d`` given, the month of that literal date;
    otherwise the current month in the user's tz (``tz_name``), UTC when tz_name is None."""
    if d is not None:
        return d.replace(day=1)
    return month_start_local(tz_name)


def _uid_param(db: Session, user_id: UUID):
    """UUID binds natively on Postgres; the SQLite GUID column stores text."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        return user_id
    return str(user_id)


def record_photo_usage(
    db: Session,
    user_id: UUID,
    *,
    photos: int = 1,
    regenerations: int = 0,
    tz_name: Optional[str] = None,
) -> None:
    """Atomically add to this user's current-month photo_usage row. Best-effort.

    ``photos`` bumps the quota total (what ``check_photo_quota`` enforces);
    ``regenerations`` breaks out the Regenerate subset for reporting. ``tz_name`` picks
    the period row (user-local month, else UTC). Never raises — a failed increment must
    not fail the generation it accompanies. Callers pass this ONLY on success (e.g.
    ``photos=stats.ready``), so a failed generate->verify never lands here.
    """
    if int(photos) <= 0 and int(regenerations) <= 0:
        return  # nothing succeeded -> nothing to record (keeps the ledger success-only)
    period: date = month_start_local(tz_name)
    sql = text(
        """
        INSERT INTO photo_usage
            (id, user_id, period_start, photos_used, regenerations, updated_at)
        VALUES (:id, :user_id, :period, :photos, :regen, :now)
        ON CONFLICT (user_id, period_start) DO UPDATE SET
            photos_used = photo_usage.photos_used + :photos,
            regenerations = photo_usage.regenerations + :regen,
            updated_at = :now
        """
    )
    try:
        db.execute(
            sql,
            {
                "id": _uid_param(db, _uuid.uuid4()),
                "user_id": _uid_param(db, user_id),
                "period": period,
                "photos": int(photos),
                "regen": int(regenerations),
                "now": datetime.utcnow(),
            },
        )
        db.commit()
    except Exception as exc:  # bookkeeping must never break the action
        logger.warning("record_photo_usage failed: %s", type(exc).__name__)
        try:
            db.rollback()
        except Exception:
            pass


def photos_used_this_month(
    db: Session, user_id: UUID, *, tz_name: Optional[str] = None
) -> int:
    """This month's photo count for the user (0 if no row). The read enforcement uses.
    ``tz_name`` selects the period row (user-local month, else UTC)."""
    row = (
        db.query(PhotoUsage)
        .filter(
            PhotoUsage.user_id == user_id,
            PhotoUsage.period_start == month_start_local(tz_name),
        )
        .one_or_none()
    )
    return int(row.photos_used) if row is not None else 0


def check_photo_quota(
    db: Session, user_id: UUID, *, tz_name: Optional[str] = None
) -> None:
    """Raise ``PhotoQuotaExceeded`` when the user is at/over their monthly cap.

    Called at the top of the ingest-commit + regenerate routes, BEFORE any staging or
    generation work. The boundary is inclusive: ``used >= limit`` rejects (so at 30/30
    the next generation is refused; at 29/30 it is allowed and may finish the batch)."""
    limit = int(settings.PHOTO_MONTHLY_QUOTA)
    used = photos_used_this_month(db, user_id, tz_name=tz_name)
    if used >= limit:
        raise PhotoQuotaExceeded(
            limit=limit, used=used, resets_at=month_reset_at(tz_name).isoformat()
        )
