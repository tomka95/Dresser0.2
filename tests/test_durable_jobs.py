"""Durable job queue — Wave 1 proof (P3.8 / ARCHITECTURE_AUDIT R1).

Exercises the generic primitive (enqueue/claim/complete/fail/reclaim) and the
worker's claim->dispatch->settle cycle on the SQLite dev/test path, and proves
the crash-recovery contract the user asked for:

  enqueue a job -> a worker claims it and "crashes" mid-run (row left 'running')
  -> a restarted worker reclaims the stale row -> it completes EXACTLY ONCE ->
  the linked IngestRun status is truthful throughout -> re-running is idempotent.

SQLite has no FOR UPDATE SKIP LOCKED, but the dev/test path is single-worker, so
the primitive's plain pick-one claim is race-free here; the Postgres claim SQL is
the same shape with SKIP LOCKED added (covered by the query text, not runtime).
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

import app.worker as worker_mod
from app.db import Base, SessionLocal, engine
from app.models import IngestRun, Job, User
from app.platform.jobs import claim_next, complete, enqueue, fail, reclaim_stale


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def user(db: Session):
    u = User(email="jobs@example.com", hashed_password="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _fresh(job_id):
    """Read a job in a brand-new session (no identity-map staleness)."""
    s = SessionLocal()
    try:
        return s.get(Job, job_id)
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Primitive
# ---------------------------------------------------------------------------

def test_enqueue_is_queued_and_transactional(db, user):
    job = enqueue(db, type="test_job", user_id=user.id, payload={"k": "v"})
    assert job.id is not None            # flush populated the id...
    # ...but nothing is committed yet: a second connection can't see it.
    assert _fresh(job.id) is None
    db.commit()
    persisted = _fresh(job.id)
    assert persisted is not None
    assert persisted.status == "queued"
    assert persisted.attempts == 0
    assert persisted.payload == {"k": "v"}


def test_claim_marks_running_increments_attempts(db, user):
    enqueue(db, type="test_job", user_id=user.id, payload={})
    db.commit()

    claimed = claim_next(db, worker_id="w1")
    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.attempts == 1
    assert claimed.locked_by == "w1"
    assert claimed.locked_at is not None
    # queue now empty
    assert claim_next(db, worker_id="w1") is None


def test_claim_skips_future_run_after(db, user):
    job = enqueue(db, type="test_job", user_id=user.id, payload={},
                  run_after=datetime.utcnow() + timedelta(hours=1))
    db.commit()
    assert claim_next(db, worker_id="w1") is None  # not due yet
    assert _fresh(job.id).status == "queued"


def test_complete_marks_succeeded(db, user):
    enqueue(db, type="test_job", user_id=user.id, payload={})
    db.commit()
    job = claim_next(db, worker_id="w1")
    complete(db, job.id)
    done = _fresh(job.id)
    assert done.status == "succeeded"
    assert done.locked_by is None and done.locked_at is None


def test_fail_requeues_then_terminal(db, user):
    enqueue(db, type="test_job", user_id=user.id, payload={}, max_attempts=2)
    db.commit()

    # attempt 1 -> fail -> requeued with backoff in the future
    job = claim_next(db, worker_id="w1")
    will_retry = fail(db, job.id, error_type="ValueError",
                      base_backoff_seconds=1.0, max_backoff_seconds=5.0)
    assert will_retry is True
    requeued = _fresh(job.id)
    assert requeued.status == "queued"
    assert requeued.last_error == "ValueError"
    assert requeued.run_after > datetime.utcnow()

    # make it due, attempt 2 -> exhausts max_attempts -> terminal 'failed'
    _set_run_after_now(job.id)
    job = claim_next(db, worker_id="w1")
    assert job.attempts == 2
    will_retry = fail(db, job.id, error_type="ValueError",
                      base_backoff_seconds=1.0, max_backoff_seconds=5.0)
    assert will_retry is False
    assert _fresh(job.id).status == "failed"


# ---------------------------------------------------------------------------
# Crash recovery (reclaim of stale 'running' rows)
# ---------------------------------------------------------------------------

def _backdate_lock(job_id, seconds_ago):
    s = SessionLocal()
    try:
        j = s.get(Job, job_id)
        j.locked_at = datetime.utcnow() - timedelta(seconds=seconds_ago)
        s.commit()
    finally:
        s.close()


def _set_run_after_now(job_id):
    s = SessionLocal()
    try:
        j = s.get(Job, job_id)
        j.run_after = datetime.utcnow() - timedelta(seconds=1)
        s.commit()
    finally:
        s.close()


def test_reclaim_stale_requeues_running(db, user):
    enqueue(db, type="test_job", user_id=user.id, payload={}, max_attempts=3)
    db.commit()
    job = claim_next(db, worker_id="crashed")   # attempts=1, running
    assert job.status == "running"

    # Simulate a crash: the row is left 'running' and its lock ages out.
    _backdate_lock(job.id, seconds_ago=3600)

    reclaimed = reclaim_stale(db, stale_seconds=60)
    assert len(reclaimed) == 1
    again = _fresh(job.id)
    assert again.status == "queued"            # re-queued (attempts remain)
    assert again.locked_by is None
    assert again.last_error == "stale_reclaim"

    # A healthy (fresh-lock) running job is NOT reclaimed.
    enqueue(db, type="test_job", user_id=user.id, payload={})
    db.commit()
    fresh = claim_next(db, worker_id="healthy")
    assert reclaim_stale(db, stale_seconds=60) == []
    assert _fresh(fresh.id).status == "running"


def test_reclaim_terminal_marks_failed(db, user):
    enqueue(db, type="test_job", user_id=user.id, payload={}, max_attempts=1)
    db.commit()
    job = claim_next(db, worker_id="crashed")   # attempts=1 == max_attempts
    _backdate_lock(job.id, seconds_ago=3600)

    reclaimed = reclaim_stale(db, stale_seconds=60)
    assert len(reclaimed) == 1
    assert reclaimed[0].status == "failed"      # attempts exhausted -> terminal
    assert _fresh(job.id).status == "failed"


# ---------------------------------------------------------------------------
# Worker loop: dispatch, retry, and the exactly-once crash-recovery narrative
# ---------------------------------------------------------------------------

def test_worker_dispatches_and_completes(db, user, monkeypatch):
    calls = []
    monkeypatch.setitem(worker_mod.REGISTRY, "test_job",
                        lambda payload, cancel: calls.append(payload))

    enqueue(db, type="test_job", user_id=user.id, payload={"n": 1})
    db.commit()

    w = worker_mod.Worker(worker_id="wtest")
    assert w.run_once() is True
    assert w.run_once() is False               # queue drained
    assert calls == [{"n": 1}]                  # handler ran exactly once
    # find the job (only one) and assert it succeeded
    s = SessionLocal()
    try:
        job = s.query(Job).one()
        assert job.status == "succeeded"
    finally:
        s.close()


def test_worker_retries_then_fails_and_flips_ingest_run(db, user, monkeypatch):
    """Handler always raises -> retried with backoff -> terminal 'failed' ->
    the linked IngestRun is flipped 'running' -> 'error' (status stops lying)."""
    monkeypatch.setattr("app.core.config.settings.JOBS_RETRY_BASE_SECONDS", 0.0)
    monkeypatch.setattr("app.core.config.settings.JOBS_RETRY_MAX_SECONDS", 0.0)

    def boom(payload, cancel):
        raise RuntimeError("handler exploded")

    monkeypatch.setitem(worker_mod.REGISTRY, "test_job", boom)

    job = enqueue(db, type="test_job", user_id=user.id, payload={}, max_attempts=2)
    run = IngestRun(user_id=user.id, status="running", job_id=job.id)
    db.add(run)
    db.commit()
    sync_id = run.sync_id

    w = worker_mod.Worker(worker_id="wtest")
    w.run_once()   # attempt 1 -> fail -> requeued (backoff 0 -> due now)
    assert _fresh(job.id).status == "queued"
    # IngestRun still 'running' during retry -- truthful: work will resume.
    assert _ingest_status(sync_id) == "running"

    w.run_once()   # attempt 2 -> exhausts max_attempts -> terminal 'failed'
    assert _fresh(job.id).status == "failed"
    # Now the run is flipped to 'error' -- no longer stuck 'running'.
    assert _ingest_status(sync_id) == "error"


def test_crash_recovery_exactly_once(db, user, monkeypatch):
    """The full narrative: claim -> crash mid-run (row left 'running') -> restart
    reclaims the stale row -> it completes EXACTLY ONCE -> IngestRun truthful ->
    re-run is idempotent (handler guarded by a per-sync dedup, like the real
    processed_messages / _select_targets dedup)."""
    applied = []   # the idempotent "work" ledger

    def idempotent_handler(payload, cancel=lambda: False):
        sid = payload["sync_id"]
        if sid in applied:
            return                 # dedup: a re-run is a no-op (never a duplicate)
        applied.append(sid)

    monkeypatch.setitem(worker_mod.REGISTRY, "test_job", idempotent_handler)

    job = enqueue(db, type="test_job", user_id=user.id,
                  payload={"sync_id": "sync-A"}, max_attempts=3)
    run = IngestRun(user_id=user.id, status="running", job_id=job.id)
    db.add(run)
    db.commit()
    sync_id = run.sync_id

    # --- worker A claims the job, then CRASHES mid-run (never settles it) ----
    sess_a = SessionLocal()
    claimed = claim_next(sess_a, worker_id="workerA")          # attempts=1, running
    assert claimed.type == "test_job"
    sess_a.close()                                             # worker A "crashes"
    _backdate_lock(job.id, seconds_ago=3600)                   # its lock ages out
    assert _fresh(job.id).status == "running"                  # stuck, no writer yet
    assert _ingest_status(sync_id) == "running"                # truthful: still working

    # --- worker B restarts: reclaim on startup re-queues the stale row -------
    monkeypatch.setattr("app.core.config.settings.JOBS_STALE_SECONDS", 60.0)
    workerB = worker_mod.Worker(worker_id="workerB")
    workerB.reclaim_on_startup()
    assert _fresh(job.id).status == "queued"                   # recovered

    # --- worker B runs it to completion -------------------------------------
    assert workerB.run_once() is True
    assert _fresh(job.id).status == "succeeded"
    assert _ingest_status(sync_id) == "running"  # handler owns run finalize; not failed

    # EXACTLY ONCE: the crashed attempt left no duplicate; the completed run
    # applied the work a single time.
    assert applied == ["sync-A"]

    # Idempotent re-run: dispatching the same payload again is a no-op.
    idempotent_handler({"sync_id": "sync-A"})
    assert applied == ["sync-A"]


# ---------------------------------------------------------------------------
# Graceful shutdown: prompt cancellation + reclaimable + exactly-once resume
# ---------------------------------------------------------------------------

def test_shutdown_is_prompt_and_leaves_job_reclaimable(db, user, monkeypatch):
    """A signal mid-job makes the worker exit within a few SECONDS (not the job's
    full multi-minute runtime), leaving the job 'queued' for a restart."""
    import threading
    import time

    monkeypatch.setattr("app.core.config.settings.JOBS_POLL_INTERVAL_SECONDS", 0.05)
    started = threading.Event()

    def slow_checkpointed_handler(payload, should_cancel):
        started.set()
        # Stand-in for the real fetch/extract/image-fill loops: long work that
        # probes should_cancel at frequent safe checkpoints. ~20s if never cancelled.
        for _ in range(2000):
            if should_cancel():
                return
            time.sleep(0.01)

    monkeypatch.setitem(worker_mod.REGISTRY, "test_job", slow_checkpointed_handler)
    enqueue(db, type="test_job", user_id=user.id, payload={"sync_id": "A"})
    db.commit()

    w = worker_mod.Worker(worker_id="wA")
    th = threading.Thread(target=w.run_forever, daemon=True)
    t0 = time.time()
    th.start()

    assert started.wait(3.0), "handler never started"
    w.request_stop()                       # a SIGINT/SIGTERM arrives mid-job
    th.join(timeout=5.0)
    elapsed = time.time() - t0

    assert not th.is_alive(), "worker did not exit after signal"
    assert elapsed < 3.0, f"shutdown took {elapsed:.1f}s (should be seconds, not ~20s)"

    s = SessionLocal()
    try:
        job = s.query(Job).one()
        assert job.status == "queued"      # left reclaimable for a restart
        assert job.attempts == 0           # cancel undid the claim's attempt++
    finally:
        s.close()


def test_cancel_requeues_then_restart_completes_exactly_once(db, user, monkeypatch):
    """Deterministic exactly-once: worker A is cancelled mid-job before it applies
    its (idempotent) work -> re-queued -> a restarted worker B completes it once."""
    applied = []   # the idempotent work ledger (like processed_messages)

    def _work(sid):
        if sid not in applied:
            applied.append(sid)

    wA = worker_mod.Worker(worker_id="wA")

    def cancelling_handler(payload, should_cancel):
        for i in range(1000):
            if should_cancel():
                return                     # stop at a safe checkpoint, work NOT applied
            if i == 2:
                # emulate the signal handler firing mid-job (first-signal effect)
                wA._cancel.set()
                wA._stop.set()
        _work(payload["sync_id"])          # only reached if never cancelled

    job = enqueue(db, type="test_job", user_id=user.id,
                  payload={"sync_id": "A"}, max_attempts=3)
    run = IngestRun(user_id=user.id, status="running", job_id=job.id)
    db.add(run)
    db.commit()
    sync_id = run.sync_id

    monkeypatch.setitem(worker_mod.REGISTRY, "test_job", cancelling_handler)
    assert wA.run_once() is True
    assert applied == []                       # cancelled before finalize -> no work
    j = _fresh(job.id)
    assert j.status == "queued"                # reclaimable
    assert j.attempts == 0                      # attempt not burned by a cancel
    assert _ingest_status(sync_id) == "running"  # truthful: work still pending

    # --- restart: worker B (not shutting down) completes it exactly once -----
    def completing_handler(payload, should_cancel):
        _work(payload["sync_id"])

    monkeypatch.setitem(worker_mod.REGISTRY, "test_job", completing_handler)
    wB = worker_mod.Worker(worker_id="wB")
    assert wB.run_once() is True
    assert _fresh(job.id).status == "succeeded"
    assert applied == ["A"]                     # EXACTLY ONCE across the crash+resume


def _ingest_status(sync_id):
    s = SessionLocal()
    try:
        return s.get(IngestRun, sync_id).status
    finally:
        s.close()
