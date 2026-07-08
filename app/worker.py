"""Durable-job worker process (P3.8 / ARCHITECTURE_AUDIT R1, Wave 1).

Run as a SECOND long-lived process alongside the uvicorn web process::

    python -m app.worker

The loop: reclaim stale jobs on startup (crash recovery) -> poll the queue ->
claim one due job (FOR UPDATE SKIP LOCKED) -> dispatch by ``type`` through the
registry -> mark it succeeded, or failed-with-backoff on an exception. Idle polls
sleep ``JOBS_POLL_INTERVAL_SECONDS``; SIGINT/SIGTERM trigger a graceful shutdown
that finishes the in-flight job before exiting.

LAYERING: this module lives at the TOP level (sibling to main.py), NOT under
app.platform, precisely because it imports the feature handlers
(app.gmail_closet / app.photo_closet) that the generic primitive
(app.platform.jobs) is walled off from. It assembles handlers the same way
main.py assembles routers -- no import-linter contract is crossed.

SECURITY / RLS: the worker uses the SAME database ``engine`` (owner role) as the
rest of the app, including the stylist connection's base role -- it opens NO
more-privileged connection and adds NO RLS bypass. Queue bookkeeping legitimately
runs on the owner connection because the jobs table is service-only (RLS, no
policy), the chat_rate_windows posture. Each handler does its per-user data work
on its own session with the existing app-level ``WHERE user_id`` scoping -- byte
-identical to what the BackgroundTasks path does today. Job payloads carry ids
only; handlers reload sensitive data from the DB. Nothing here logs a payload.
"""
from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
from typing import Callable, Dict, Optional
from uuid import UUID

from app.core.config import settings
from app.db import SessionLocal
from app.platform.jobs import claim_next, complete, fail, reclaim_stale, requeue

logger = logging.getLogger(__name__)

# A handler takes the job's opaque payload (ids only) plus a ``should_cancel``
# probe, and does the work. It OWNS its own DB session and MAY raise -- the loop
# turns a raised exception into a retry-with-backoff (or a terminal failure once
# attempts are exhausted). ``should_cancel()`` returns True once graceful shutdown
# has been requested; a cooperative handler threads it into its long loops and
# stops at the next safe checkpoint, leaving partial (idempotent) progress durable.
ShouldCancel = Callable[[], bool]
Handler = Callable[[dict, ShouldCancel], None]


# ---------------------------------------------------------------------------
# Handlers -- thin adapters onto the existing, already-idempotent cores.
# ---------------------------------------------------------------------------
# Each mirrors the body of the legacy *_background function but, unlike those,
# lets an UNEXPECTED error propagate so the queue can retry it. The cores
# themselves still own IngestRun truthfulness for the non-crash path (they finalize
# 'completed'/'error' internally); the worker owns the crash path (reclaim below).

def _handle_gmail_ingest(payload: dict, should_cancel: ShouldCancel) -> None:
    from app.gmail_closet.fetch_service import run_full_ingest

    user_id = UUID(payload["user_id"])
    sync_id = UUID(payload["sync_id"])
    db = SessionLocal()
    try:
        # should_cancel is threaded into every phase (fetch/extract/image-fill) and
        # checked at message/item boundaries, so a graceful shutdown aborts the
        # minutes-long slow-tier work within seconds instead of running to the end.
        run_full_ingest(user_id=user_id, db=db, sync_id=sync_id, should_cancel=should_cancel)
    finally:
        db.close()


def _handle_photo_generation(payload: dict, should_cancel: ShouldCancel) -> None:
    from app.photo_closet.generation_service import (
        run_generation_self_heal,
        run_photo_generation,
    )

    user_id = UUID(payload["user_id"])
    sync_id = UUID(payload["sync_id"])
    db = SessionLocal()
    try:
        # NOTE: photo generation is a bounded thread-pool over candidates and is not
        # yet cooperatively cancellable mid-batch (Wave 2). It still shuts down
        # promptly via the second-signal escape hatch, and the reclaim sweep +
        # _select_targets idempotency make an interrupted run safe to resume.
        run_photo_generation(user_id, db, sync_id)
        # Opportunistic self-heal of this user's OTHER stale targets, mirroring the
        # legacy generate_background tail (exclude THIS run's fresh failures).
        run_generation_self_heal(user_id, db, exclude_sync_id=sync_id)
    finally:
        db.close()


REGISTRY: Dict[str, Handler] = {
    "gmail_ingest": _handle_gmail_ingest,
    "photo_generation": _handle_photo_generation,
}


# ---------------------------------------------------------------------------
# IngestRun reconciliation -- make GET /*/ingest/status truthful after a crash.
# ---------------------------------------------------------------------------

def _fail_linked_run(job_id: UUID) -> None:
    """When a job is terminally failed, flip its still-'running' IngestRun to
    'error'. Late import of IngestRun keeps this module's import graph flat; the
    owner connection is correct (ingest_runs is per-user RLS, worker is owner)."""
    from app.models.ingestion import IngestRun

    db = SessionLocal()
    try:
        updated = (
            db.query(IngestRun)
            .filter(IngestRun.job_id == job_id, IngestRun.status == "running")
            .update({"status": "error"}, synchronize_session=False)
        )
        db.commit()
        if updated:
            logger.info("job=%s terminally failed -> IngestRun flipped to 'error'", job_id)
    except Exception:
        db.rollback()
        logger.exception("failed to reconcile IngestRun for job=%s", job_id)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------

class Worker:
    def __init__(self, worker_id: Optional[str] = None) -> None:
        self.worker_id = worker_id or settings.JOBS_WORKER_ID or socket.gethostname()
        self._stop = threading.Event()      # stop claiming NEW jobs
        self._cancel = threading.Event()    # abort the CURRENTLY running job
        self._signals = 0                   # signal count -> second one is a hard exit

    def request_stop(self, *_args) -> None:
        """Signal handler. First SIGINT/SIGTERM: stop claiming new jobs AND ask the
        in-flight job to abort at its next safe checkpoint (prompt, cooperative).
        Second signal: immediate process exit -- the operator escape hatch."""
        self._signals += 1
        if self._signals >= 2:
            logger.warning("worker %s: second signal -> immediate exit", self.worker_id)
            os._exit(130)
        logger.info(
            "worker %s: shutdown requested -> not claiming new jobs; "
            "signalling in-flight job to abort (send signal again to force-exit)",
            self.worker_id,
        )
        self._stop.set()
        self._cancel.set()

    def _should_cancel(self) -> bool:
        return self._cancel.is_set()

    # -- crash recovery on startup ------------------------------------------
    def reclaim_on_startup(self) -> None:
        db = SessionLocal()
        try:
            reclaimed = reclaim_stale(db, stale_seconds=settings.JOBS_STALE_SECONDS)
            # Snapshot terminally-failed ids BEFORE the session closes (detaching
            # the ORM rows would make attribute access raise).
            terminal = [job.id for job in reclaimed if job.status == "failed"]
        finally:
            db.close()
        for job_id in terminal:
            _fail_linked_run(job_id)

    # -- one claim->dispatch->settle cycle; returns True if a job was run ----
    def run_once(self) -> bool:
        db = SessionLocal()
        try:
            job = claim_next(db, worker_id=self.worker_id)
            if job is None:
                return False
            # Snapshot the primitives before releasing the queue session, so the
            # (possibly multi-minute) handler holds no queue connection/txn.
            job_id = job.id
            job_type = job.type
            attempt = job.attempts
            payload = dict(job.payload or {})
        finally:
            db.close()

        handler = REGISTRY.get(job_type)
        if handler is None:
            logger.error("job=%s unknown type '%s' -> failing", job_id, job_type)
            self._settle_failure(job_id, "UnknownJobType")
            return True

        logger.info("job=%s type=%s attempt=%d/%s: dispatching",
                    job_id, job_type, attempt, settings.JOBS_MAX_ATTEMPTS)
        t0 = time.time()
        try:
            handler(payload, self._should_cancel)
        except Exception as exc:
            elapsed = time.time() - t0
            # If we're shutting down, a raised exception is almost certainly a
            # side effect of the abort (a torn-down connection, a cancelled call),
            # not a genuine job failure -- re-queue it rather than burning an
            # attempt. Otherwise settle it as a real failure (retry/backoff).
            if self._cancel.is_set():
                logger.info("job=%s type=%s: aborted after %.1fs (shutdown) -> re-queued",
                            job_id, job_type, elapsed)
                self._requeue(job_id, reason="cancelled")
            else:
                # last_error carries the TYPE NAME only (never the body) -- persisted,
                # SQL-queryable column.
                logger.error("job=%s type=%s: FAILED after %.1fs (%s)",
                             job_id, job_type, elapsed, type(exc).__name__)
                self._settle_failure(job_id, type(exc).__name__)
            return True

        elapsed = time.time() - t0
        # A cooperative handler returns cleanly when cancelled (its loops just
        # stopped early). If shutdown was requested, re-queue for exactly-once
        # resume instead of marking the (incomplete) job succeeded.
        if self._cancel.is_set():
            logger.info("job=%s type=%s: cancelled at checkpoint after %.1fs -> re-queued (reclaimable)",
                        job_id, job_type, elapsed)
            self._requeue(job_id, reason="cancelled")
            return True

        db2 = SessionLocal()
        try:
            complete(db2, job_id)
        finally:
            db2.close()
        logger.info("job=%s type=%s: SUCCEEDED in %.1fs", job_id, job_type, elapsed)
        return True

    def _requeue(self, job_id: UUID, *, reason: str) -> None:
        db = SessionLocal()
        try:
            requeue(db, job_id, reason=reason)
        finally:
            db.close()

    def _settle_failure(self, job_id: UUID, error_type: str) -> None:
        db = SessionLocal()
        try:
            will_retry = fail(
                db,
                job_id,
                error_type=error_type,
                base_backoff_seconds=settings.JOBS_RETRY_BASE_SECONDS,
                max_backoff_seconds=settings.JOBS_RETRY_MAX_SECONDS,
            )
        finally:
            db.close()
        if not will_retry:
            _fail_linked_run(job_id)

    # -- main loop ----------------------------------------------------------
    def run_forever(self) -> None:
        logger.info(
            "worker %s: starting (poll=%.1fs stale=%.0fs)",
            self.worker_id, settings.JOBS_POLL_INTERVAL_SECONDS, settings.JOBS_STALE_SECONDS,
        )
        self.reclaim_on_startup()
        while not self._stop.is_set():
            try:
                did_work = self.run_once()
            except Exception:
                # A loop-level error (e.g. DB blip) must not kill the worker;
                # back off one poll interval and retry.
                logger.exception("worker %s: loop iteration error", self.worker_id)
                did_work = False
            if not did_work:
                # Interruptible idle sleep -- wakes immediately on shutdown.
                self._stop.wait(settings.JOBS_POLL_INTERVAL_SECONDS)
        logger.info("worker %s: stopped cleanly", self.worker_id)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    worker = Worker()
    signal.signal(signal.SIGINT, worker.request_stop)
    signal.signal(signal.SIGTERM, worker.request_stop)
    worker.run_forever()


if __name__ == "__main__":
    main()
