"""Durable job queue (P3.8 / ARCHITECTURE_AUDIT R1, Wave 1).

The ``jobs`` table backs the Postgres-native durable queue that replaces the
process-bound ``BackgroundTasks``/daemon-thread dispatch for the two already-
idempotent background jobs (gmail_ingest, photo_generation). It is claimed via
``SELECT ... FOR UPDATE SKIP LOCKED`` and reclaimed after a crash by a stale-lock
sweep — see app/platform/jobs/ (the generic primitive) and app/worker.py (the
loop). Behaviour is gated behind per-type feature flags (default OFF), so this
table is inert until a flag is flipped.

SERVICE-ONLY, no user-facing route ever reads/writes a job row directly: the
owning migration (0026) ships it RLS-enabled with NO policy (deny-all for
anon/authenticated), the same posture as chat_rate_windows / image_blobs. RLS is
not expressible in the ORM and is owned by the migration.

SECURITY: ``payload`` carries IDS ONLY (e.g. {"user_id", "sync_id"}) — never
tokens, email bodies, image bytes, or any PII; the job reloads sensitive data
from the DB inside the handler. ``last_error`` carries ``type(exc).__name__``
ONLY (never the exception body), a deliberately tighter bar than the rotating log
lines since this is a persisted, SQL-queryable column.

Split style matches the rest of app/models/* (P3.2, R4); re-exported from
app.models for a flat import surface.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint, Column, ForeignKey, Index, Integer, Text,
)

from app.db import Base, GUID
from app.models._shared import _jsonb, _tstz


class Job(Base):
    """One durable unit of background work: enqueue -> claim -> succeed/fail.

    status lifecycle (CHECK below):
      queued    -- waiting; claimable once run_after <= now()
      running   -- claimed by a worker (locked_by/locked_at set)
      succeeded -- terminal, handler returned cleanly
      failed    -- terminal, retries exhausted (attempts >= max_attempts)

    A crashed worker leaves a row stuck in 'running'; the reclaim sweep
    (app/platform/jobs) detects it via a stale locked_at and re-queues it (or
    marks it 'failed' if attempts are exhausted). Because both Wave-1 handlers
    are idempotent at the data layer (processed_messages / _select_targets
    dedup), a re-run of a reclaimed job is a no-op, never a duplicate.
    """

    __tablename__ = "jobs"

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed')", name="status"),
        # The claim query: WHERE status='queued' AND run_after <= now()
        # ORDER BY created_at LIMIT 1. Leading status column keeps it an index
        # range scan; run_after orders the eligible slice.
        Index("idx_jobs_claim", "status", "run_after"),
        Index("idx_jobs_user_id", "user_id"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    # Registry key -> handler (app/worker.py). 'gmail_ingest' | 'photo_generation'
    # in Wave 1; extensible (enrichment/distill are Wave 2).
    type = Column(Text, nullable=False)

    # Owning user. Column (not just payload) so a deleted user's queued jobs
    # CASCADE away, and for the chat_rate_windows service-only-with-user_id
    # precedent. NOT a per-user-readable surface (RLS deny-all, see module doc).
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # IDS/params ONLY -- never tokens/PII/bytes (see module doc).
    payload = Column(_jsonb(), nullable=False, default=dict)

    status = Column(Text, nullable=False, default="queued")

    attempts = Column(Integer, nullable=False, default=0)

    max_attempts = Column(Integer, nullable=False, default=3)

    # Backoff / delayed scheduling: a row is invisible to the claim query until
    # run_after <= now(). Bumped by the exponential backoff on a failed attempt.
    run_after = Column(_tstz(), default=datetime.utcnow, nullable=False)

    # Lease bookkeeping. locked_at drives stale detection (running rows whose
    # locked_at is older than the stale threshold are reclaimable). locked_by is
    # the worker id/hostname (observability only).
    locked_at = Column(_tstz(), nullable=True)

    locked_by = Column(Text, nullable=True)

    # type(exc).__name__ ONLY -- never the exception body (see module doc).
    last_error = Column(Text, nullable=True)

    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)

    updated_at = Column(_tstz(), default=datetime.utcnow, onupdate=datetime.utcnow,
                        nullable=False)
