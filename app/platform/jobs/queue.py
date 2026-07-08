"""The durable-queue primitive: enqueue / claim / complete / fail / reclaim.

Portable across the two dialects this codebase runs on:
  - PostgreSQL (Supabase, production): the claim uses ``FOR UPDATE SKIP LOCKED``
    so N concurrent workers claim disjoint jobs with zero extra coordination.
  - SQLite (LOCAL_DB dev/test): no SKIP LOCKED, but the dev/test path is
    single-worker, so a plain "pick one, mark it" claim is race-free enough. The
    same enqueue/complete/fail/reclaim SQL is portable as-is.

Timestamps follow the codebase-wide convention: naive UTC (``datetime.utcnow``),
exactly what every ORM model default uses. Supabase runs UTC, so naive values
round-trip through ``timestamptz`` unambiguously; SQLite stores them naive. We
never mix aware and naive within a comparison.

SECURITY: this layer is generic. It moves ``payload`` dicts verbatim and stores
``last_error`` strings verbatim -- callers are responsible for keeping ids-only
in payloads and type-name-only in error strings (enforced at the call sites and
documented on the Job model). Nothing here logs a payload.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.jobs import Job

logger = logging.getLogger(__name__)


def _dialect(session: Session) -> str:
    bind = session.get_bind()
    return bind.dialect.name if bind is not None else "postgresql"


def _backoff(attempts: int, base_seconds: float, max_seconds: float) -> timedelta:
    """Capped exponential backoff. ``attempts`` is the count AFTER this attempt
    (claim increments it), so the first retry waits ~base seconds."""
    exp = base_seconds * (2 ** max(0, attempts - 1))
    return timedelta(seconds=min(exp, max_seconds))


# ---------------------------------------------------------------------------
# enqueue -- TRANSACTIONAL (no commit; caller owns the transaction boundary)
# ---------------------------------------------------------------------------

def enqueue(
    session: Session,
    *,
    type: str,
    user_id: UUID,
    payload: dict,
    max_attempts: int = 3,
    run_after: Optional[datetime] = None,
) -> Job:
    """Insert a queued job and return it (id populated via flush).

    Does NOT commit: the caller commits it in the SAME transaction as its own
    rows (e.g. the IngestRun insert + ingest_runs.job_id link), so the job and
    the state it represents are committed atomically -- there is no window where
    one exists without the other.

    ``payload`` must carry IDS/params ONLY (no tokens, bodies, or PII).
    """
    job = Job(
        type=type,
        user_id=user_id,
        payload=payload,
        status="queued",
        max_attempts=max_attempts,
        run_after=run_after or datetime.utcnow(),
    )
    session.add(job)
    session.flush()  # populate job.id without committing
    return job


# ---------------------------------------------------------------------------
# claim_next -- FOR UPDATE SKIP LOCKED (Postgres) / pick-one (SQLite)
# ---------------------------------------------------------------------------

_CLAIM_PG = text(
    """
    WITH next_job AS (
        SELECT id FROM jobs
        WHERE status = 'queued' AND run_after <= now()
        ORDER BY created_at ASC
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    UPDATE jobs
    SET status = 'running',
        locked_by = :worker_id,
        locked_at = now(),
        attempts = attempts + 1,
        updated_at = now()
    FROM next_job
    WHERE jobs.id = next_job.id
    RETURNING jobs.id
    """
)


def claim_next(session: Session, *, worker_id: str) -> Optional[Job]:
    """Atomically claim the oldest due job, or return None if none are ready.

    Commits the claim immediately so the 'running' lock is durable and visible
    to other workers / the reclaim sweep. Increments ``attempts`` as part of the
    same atomic update.
    """
    if _dialect(session) == "postgresql":
        row = session.execute(_CLAIM_PG, {"worker_id": worker_id}).first()
        session.commit()
        if row is None:
            return None
        job_id = row[0]
    else:
        # SQLite dev/test: single-worker, so select-then-update is race-free.
        now = datetime.utcnow()
        picked = (
            session.query(Job)
            .filter(Job.status == "queued", Job.run_after <= now)
            .order_by(Job.created_at.asc())
            .first()
        )
        if picked is None:
            session.commit()
            return None
        picked.status = "running"
        picked.locked_by = worker_id
        picked.locked_at = now
        picked.attempts = picked.attempts + 1
        picked.updated_at = now
        session.commit()
        job_id = picked.id

    return session.get(Job, job_id)


# ---------------------------------------------------------------------------
# complete / fail
# ---------------------------------------------------------------------------

def complete(session: Session, job_id: UUID) -> None:
    """Mark a job succeeded (terminal) and clear its lock."""
    job = session.get(Job, job_id)
    if job is None:
        return
    job.status = "succeeded"
    job.locked_by = None
    job.locked_at = None
    job.updated_at = datetime.utcnow()
    session.commit()


def fail(
    session: Session,
    job_id: UUID,
    *,
    error_type: str,
    base_backoff_seconds: float,
    max_backoff_seconds: float,
) -> bool:
    """Record a failed attempt. Re-queue with capped exponential backoff if
    attempts remain, else mark 'failed' (terminal). Returns True if the job will
    be retried, False if it is now terminally failed.

    ``error_type`` should be ``type(exc).__name__`` ONLY (never the exception
    body) -- this lands in a persisted, SQL-queryable column.
    """
    job = session.get(Job, job_id)
    if job is None:
        return False
    now = datetime.utcnow()
    job.last_error = error_type
    job.locked_by = None
    job.locked_at = None
    job.updated_at = now
    if job.attempts >= job.max_attempts:
        job.status = "failed"
        will_retry = False
    else:
        job.status = "queued"
        job.run_after = now + _backoff(job.attempts, base_backoff_seconds, max_backoff_seconds)
        will_retry = True
    session.commit()
    return will_retry


def requeue(session: Session, job_id: UUID, *, reason: str = "cancelled") -> None:
    """Return a claimed job to 'queued' WITHOUT counting the attempt.

    For COOPERATIVE CANCELLATION (graceful worker shutdown): the work was
    interrupted at a safe checkpoint, not failed, so it must not erode the retry
    budget -- the claim's attempts++ is undone. Due immediately (run_after=now),
    so a restarting worker picks it straight back up and finishes it exactly-once
    (partial progress is idempotent). ``reason`` is a queryable breadcrumb (a
    graceful marker, not a failure).
    """
    job = session.get(Job, job_id)
    if job is None:
        return
    now = datetime.utcnow()
    job.status = "queued"
    job.locked_by = None
    job.locked_at = None
    job.attempts = max(0, job.attempts - 1)
    job.run_after = now
    job.last_error = reason
    job.updated_at = now
    session.commit()


# ---------------------------------------------------------------------------
# reclaim_stale -- crash recovery (the writer R1 lacked)
# ---------------------------------------------------------------------------

def reclaim_stale(session: Session, *, stale_seconds: float) -> List[Job]:
    """Reclaim jobs stuck 'running' whose lock is older than ``stale_seconds``
    (their worker died mid-run). Each is re-queued if attempts remain, else
    marked 'failed'. Returns the reclaimed Job rows (post-update state) so the
    caller can reconcile any linked side-state (e.g. flip a dead run to 'error').

    A crash is not the job's fault, so a re-queued row is due IMMEDIATELY
    (run_after untouched -- it was set in the past at enqueue) rather than
    penalized with backoff; backoff is reserved for the exception-retry path.

    Idempotent and cheap: a healthy running job (fresh locked_at) is never
    touched; running this every poll cycle is safe.
    """
    cutoff = datetime.utcnow() - timedelta(seconds=stale_seconds)
    stale = (
        session.query(Job)
        .filter(Job.status == "running", Job.locked_at.isnot(None), Job.locked_at < cutoff)
        .all()
    )
    if not stale:
        return []

    now = datetime.utcnow()
    reclaimed: List[Job] = []
    for job in stale:
        job.last_error = job.last_error or "stale_reclaim"
        job.locked_by = None
        job.locked_at = None
        job.updated_at = now
        job.status = "failed" if job.attempts >= job.max_attempts else "queued"
        reclaimed.append(job)
    session.commit()
    logger.info("reclaim_stale: recovered %d stale running job(s)", len(reclaimed))
    return reclaimed
