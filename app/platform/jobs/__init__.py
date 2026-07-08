"""Generic durable-queue primitive (P3.8 / ARCHITECTURE_AUDIT R1, Wave 1).

A Postgres-native job queue, hand-rolled (no broker, no Redis) on the same
database every worker already shares. This package is BUSINESS-LOGIC-FREE: it
knows only ``Job`` rows keyed by a ``type`` string and an opaque ``payload``
dict. It never imports a feature layer (gmail_closet / photo_closet / services /
ranking / monetization / api), so it sits cleanly inside app.platform and is
covered by the existing ``platform-depends-on-nothing-upward`` contract with no
new rule needed. The registry (type -> handler) and the poll loop live OUTSIDE
this wall, in app/worker.py.

Exposed operations:
  enqueue        -- insert a queued job (TRANSACTIONAL: does not commit; the
                    caller commits it in the same transaction as its own rows,
                    e.g. the IngestRun insert -> no dual-write/outbox problem).
  claim_next     -- FOR UPDATE SKIP LOCKED claim of one due job (its own txn).
  complete       -- mark a job succeeded.
  fail           -- mark a job for retry with capped exponential backoff, or
                    'failed' once attempts are exhausted.
  reclaim_stale  -- crash recovery: re-queue (or fail) rows stuck 'running' whose
                    lock is older than the stale threshold. This is the writer
                    that did not exist before R1.
"""
from app.platform.jobs.queue import (
    claim_next,
    complete,
    enqueue,
    fail,
    reclaim_stale,
    requeue,
)

__all__ = [
    "enqueue",
    "claim_next",
    "complete",
    "fail",
    "requeue",
    "reclaim_stale",
]
