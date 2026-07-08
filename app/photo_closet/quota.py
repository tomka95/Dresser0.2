"""Photo-quota ledger — the counter SCRUM-44 enforcement will read.

The free tier is "30 photos a month". Enforcement is NOT built yet; this module owns
the monthly counter so quota-consuming photo actions (today: Regenerate) durably record
against it, and SCRUM-44 can later read/enforce with no wiring change.

Mirrors app/services/stylist/limits.record_turn_usage: an atomic ON CONFLICT upsert on
the (user_id, period_start) unique key so the count stays correct across the web + worker
processes. period_start is the FIRST day of the usage month (UTC). Best-effort — a
bookkeeping failure must never break the user-facing action it accompanies.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import PhotoUsage

logger = logging.getLogger(__name__)


def month_start(d: date | None = None) -> date:
    """First day of the (UTC) month for ``d`` (defaults to today)."""
    ref = d or datetime.utcnow().date()
    return ref.replace(day=1)


def _uid_param(db: Session, user_id: UUID):
    """UUID binds natively on Postgres; the SQLite GUID column stores text."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        return user_id
    return str(user_id)


def record_photo_usage(
    db: Session, user_id: UUID, *, photos: int = 1, regenerations: int = 0
) -> None:
    """Atomically add to this user's current-month photo_usage row. Best-effort.

    ``photos`` bumps the quota total (what SCRUM-44 will enforce); ``regenerations``
    breaks out the Regenerate subset for reporting. Never raises — a failed increment
    must not fail the regenerate/commit it accompanies.
    """
    period: date = month_start()
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


def photos_used_this_month(db: Session, user_id: UUID) -> int:
    """This month's photo count for the user (0 if no row). The read SCRUM-44 enforces."""
    row = (
        db.query(PhotoUsage)
        .filter(PhotoUsage.user_id == user_id, PhotoUsage.period_start == month_start())
        .one_or_none()
    )
    return int(row.photos_used) if row is not None else 0
