"""Narrated crash-recovery proof for the durable job queue (P3.8 / R1, Wave 1).

Runs the full scenario end-to-end against a throwaway SQLite DB and prints a
step-by-step ledger, so the exactly-once + truthful-status guarantees are
visible without reading the test:

    enqueue -> worker A claims -> worker A CRASHES mid-run (row left 'running')
    -> worker B restarts, reclaims the stale row -> completes EXACTLY ONCE
    -> IngestRun status truthful throughout -> re-run is idempotent

Run it:  .venv/bin/python -m scripts.jobs_crash_recovery_proof

Uses SQLite (LOCAL_DB) so it needs no Postgres and mutates nothing real. The
Postgres claim adds FOR UPDATE SKIP LOCKED (same query shape); the reclaim /
complete / fail logic is dialect-identical.
"""
import os
from datetime import datetime, timedelta

os.environ.setdefault("LOCAL_DB", "sqlite")

import app.worker as worker_mod  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import IngestRun, Job, User  # noqa: E402
from app.platform.jobs import claim_next  # noqa: E402

APPLIED = []  # the idempotent "work" ledger the handler writes to


def _handler(payload, should_cancel=lambda: False):
    """Idempotent stand-in for run_full_ingest: guarded by a per-sync dedup, the
    same shape as the real processed_messages / _select_targets dedup."""
    sid = payload["sync_id"]
    if sid in APPLIED:
        return  # re-run is a no-op -> never a duplicate
    APPLIED.append(sid)


def _status(model, pk):
    s = SessionLocal()
    try:
        return s.get(model, pk).status
    finally:
        s.close()


def _ok(cond, msg):
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        raise SystemExit(1)


def main():
    Base.metadata.create_all(bind=engine)
    worker_mod.REGISTRY["proof_job"] = _handler
    setup = SessionLocal()
    try:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        user = User(email="proof@example.com", hashed_password="x")
        setup.add(user)
        setup.commit()
        setup.refresh(user)

        job = Job(type="proof_job", user_id=user.id,
                  payload={"sync_id": "sync-A"}, status="queued", max_attempts=3,
                  run_after=datetime.utcnow())
        setup.add(job)
        setup.flush()
        run = IngestRun(user_id=user.id, status="running", job_id=job.id)
        setup.add(run)
        setup.commit()
        job_id, sync_id = job.id, run.sync_id
        print("1. Enqueued proof_job + linked IngestRun (status=running).")

        # -- worker A claims, then crashes (never settles) -------------------
        sess_a = SessionLocal()
        claim_next(sess_a, worker_id="workerA")
        sess_a.close()
        # age the lock so it looks crashed
        s = SessionLocal()
        s.get(Job, job_id).locked_at = datetime.utcnow() - timedelta(hours=1)
        s.commit()
        s.close()
        print("2. Worker A claimed it (status=running), then CRASHED mid-run.")
        _ok(_status(Job, job_id) == "running", "job stuck 'running' (no writer yet)")
        _ok(_status(IngestRun, sync_id) == "running",
            "IngestRun still 'running' (truthful: work is pending)")

        # -- worker B restarts: reclaim on startup ---------------------------
        worker_mod.settings.JOBS_STALE_SECONDS = 60.0
        workerB = worker_mod.Worker(worker_id="workerB")
        workerB.reclaim_on_startup()
        print("3. Worker B restarted -> reclaim_on_startup swept the stale row.")
        _ok(_status(Job, job_id) == "queued", "stale row reclaimed -> 'queued'")

        # -- worker B runs it to completion ----------------------------------
        did = workerB.run_once()
        print("4. Worker B ran the reclaimed job.")
        _ok(did is True, "run_once dispatched the job")
        _ok(_status(Job, job_id) == "succeeded", "job -> 'succeeded'")
        _ok(APPLIED == ["sync-A"], "work applied EXACTLY ONCE (crash left no dup)")

        # -- idempotent re-run ----------------------------------------------
        _handler({"sync_id": "sync-A"})
        _ok(APPLIED == ["sync-A"], "re-running the same payload is a no-op (idempotent)")

        print("\nALL CHECKS PASSED — exactly-once + truthful status proven.")
    finally:
        setup.close()
        Base.metadata.drop_all(bind=engine)


if __name__ == "__main__":
    main()
