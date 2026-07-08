# Durable Job Queue — Design (P3.8, ARCHITECTURE_AUDIT R1)

**Status: Phase A, read-only audit + proposal. No code changed. No migration applied.**
Branch `feat/durable-jobs` off main.

---

## 1. Inventory — every fire-and-forget dispatch site

Six dispatch sites total (`rg -n "add_task\(|threading\.Thread\("`), four via `BackgroundTasks`, two via raw daemon threads. All six create their own DB session and swallow every exception (`except Exception: logger.error(...)`) — none can ever crash the request, but none can ever be *retried* either: once the process that owns the thread/threadpool dies, the work is gone and nothing notices.

| # | Site | Function | What it does | Multi-min? | Cost | User-visible status? | Idempotent today? |
|---|------|----------|---------------|:---:|---|:---:|---|
| 1 | `gmail_ingest.py:229` | `ingest_background` (fetch_service.py:589) | Full Gmail sync: list→fetch→filter→extract(LLM)→image-fill | **Yes** (minutes) | LLM + Serper $ | **Yes** — `GET /gmail/ingest/status` polls `IngestRun.status` | **Yes.** `processed_messages` UNIQUE(user_id,message_id) + `ON CONFLICT DO UPDATE` (fetch_service.py:266) and `ingest_candidates` UNIQUE(user_id,source_line_key) mean a from-scratch re-run of `run_full_ingest` skips everything already done. |
| 2 | `photo_ingest.py:277` | `generate_background` (generation_service.py:157) | Per-candidate image generation + verify, tied to the same `IngestRun`/sync_id pattern | Yes (seconds–minutes, N images) | Paid image-gen $ | Yes — same `IngestRun.status` | **Yes, explicitly.** `_select_targets` (generation_service.py:184) docstring: *"Excludes 'ready'/'failed' so re-running is idempotent."* |
| 3 | `chat_ingest.py:137` | `generate_background` (same function as #2) | Chat→closet photo bridge, identical dispatch shape via a raw thread instead of `BackgroundTasks` (already off the request thread — SSE worker) | same as #2 | same as #2 | same as #2 | same as #2 |
| 4 | `gmail_ingest.py:352` + `closet.py:278` | `enrich_items_background` (enrichment.py:489) | Tier-1/2 attribute enrichment + embed for just-written items | No (seconds) | Cheap (Flash-Lite) | No dedicated status endpoint | **Safe but not free.** No "already enriched" skip — re-running re-calls the LLM and rewrites `attributes_json`/embeddings. Never regresses a `user_edited` field (enforced in `enrich_item`), so a duplicate run is harmless, just wasted spend. |
| 5 | `chat.py:226` | `distill_background` (distill.py:356) | Post-turn preference-signal mining | No (seconds) | Cheap (Flash-Lite) | No status endpoint | Append-only signal mining; a lost/duplicate run only shifts how many `preference_signals` rows exist, never corrupts state. |

**The R1 symptom, concretely:** `IngestRun.status` is set `'running'` at request time (gmail_ingest.py:224, ingest_service.py:643) and flipped to `'completed'`/`'error'` only at the *end* of the phase (fetch_service.py:449/477, extraction_service.py:396/407/514/543, generation_service.py:446). There is no third writer. If the worker process dies between those two points, the row is stuck `'running'` forever and `GET /gmail/ingest/status` (gmail_ingest.py:238) reports it as such indefinitely — confirmed by reading the endpoint: it's a plain `SELECT`, no liveness cross-check.

**A second, independent bug the redesign fixes for free:** the "prevent duplicate concurrent syncs" check (gmail_ingest.py:208-224) is check-then-insert with no locking — two near-simultaneous requests can both see "nothing running" and both create an `IngestRun`. Not R1, but the same migration's dedup mechanism (§3) closes it.

**Key finding that shapes the whole design:** three of the four background functions (#1, #2/#3) are *already* idempotent at the data layer, by deliberate prior design (the docstrings say so explicitly). The durable-queue layer therefore does **not** need to invent idempotency — it only needs to reliably *re-invoke the same already-safe function* after a crash, and make the status row that users poll stop lying. That's a much narrower, lower-risk problem than it first looks.

---

## 2. Recommended design: Postgres-backed queue, `SELECT ... FOR UPDATE SKIP LOCKED`

**Recommendation: a `jobs` table in the same Supabase Postgres database, claimed via `FOR UPDATE SKIP LOCKED`. No new infrastructure (no Redis, no broker, no AWS service).**

### Why, vs a broker (Celery/Redis, SQS, RabbitMQ)

- This stack has an explicit standing decision: *"Redis is not part of this stack"* (config.py comment, `CHAT_RATE_LIMIT_PER_MINUTE` section) — precedent for "the DB is the one shared, durable store every worker already has."
- No AWS footprint exists to hang SQS off (boto3 here talks only to Supabase's S3-compatible storage).
- A broker is a new service to provision, monitor, secure, and pay for — directly against the brief ("without new infra we must operate").
- **Transactional enqueue for free.** Because the job row lives in the same database as `IngestRun`, an enqueue can happen in the *same transaction* that creates the `IngestRun` row — the classic dual-write/outbox problem (row committed, message lost, or vice versa) doesn't exist here.
- **Operationally transparent.** `SELECT * FROM jobs WHERE status='claimed' AND lease_expires_at < now()` is a query anyone with DB access can run directly — no opaque broker internals to reason about during an incident.
- `FOR UPDATE SKIP LOCKED` gives safe concurrent claiming across N worker processes with zero extra coordination infra — this is precisely what "scales horizontally later" needs, and it costs nothing extra today with one worker.
- Honest downside: Postgres-queue is poll-based (added latency = poll interval, not push-notified) and would eventually bottleneck at very high throughput. Neither matters here — these are multi-minute background jobs where a few seconds of poll latency is noise, and this app is nowhere near broker-necessitating throughput. If that ever changes, the job-table *interface* (enqueue/claim/complete) is the seam to swap the backend behind — a contained, later migration, not a reason to over-build now.

This pattern is well-trodden (pg-boss, graphile-worker, Oban, procrastinate all do exactly this on Postgres). I'd hand-roll a small version (enqueue/claim/complete/reclaim is ~150 lines of SQL + a thin Python wrapper) rather than pull in a new dependency — it matches this codebase's existing style of few, well-understood dependencies, and the mechanism is simple enough that owning it outright beats debugging someone else's abstraction. If it grows unwieldy, `procrastinate` (Python/Postgres-native, no new infra) is the fallback to reach for rather than a broker.

### Schema

```sql
CREATE TABLE jobs (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type         text NOT NULL,                 -- 'gmail_ingest' | 'photo_generation' | 'enrichment' (extensible)
    user_id          uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    payload          jsonb NOT NULL DEFAULT '{}',   -- ids/params ONLY -- see §6
    status           text NOT NULL DEFAULT 'queued', -- queued | claimed | running | completed | failed | dead
    attempts         integer NOT NULL DEFAULT 0,
    max_attempts     integer NOT NULL DEFAULT 3,     -- lower (e.g. 2) for enrichment: retries aren't free (§1)
    dedup_key        text,                            -- e.g. 'gmail_ingest:{user_id}' -- see below
    claimed_by       text,                            -- worker id/hostname, observability only
    claimed_at       timestamptz,
    lease_expires_at timestamptz,                     -- claim expires -> reclaimable
    run_after        timestamptz NOT NULL DEFAULT now(), -- backoff/delay scheduling
    last_error       text,                            -- type(exc).__name__ ONLY -- see §6
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    completed_at     timestamptz
);

-- Atomic duplicate-sync prevention (replaces the check-then-insert race in
-- gmail_ingest.py today): only one ACTIVE job per dedup_key.
CREATE UNIQUE INDEX jobs_dedup_key_active_key ON jobs(dedup_key)
    WHERE status IN ('queued','claimed','running');

CREATE INDEX idx_jobs_claim ON jobs(status, run_after) WHERE status = 'queued';
CREATE INDEX idx_jobs_user_id ON jobs(user_id);
CREATE INDEX idx_jobs_lease_expires ON jobs(status, lease_expires_at) WHERE status IN ('claimed','running');

ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
-- NO policy: service-only. jobs is pure internal scheduling state -- no
-- user-facing route ever reads/writes a job row directly (status is read via
-- the existing IngestRun/status endpoints, see §3). Same posture as the
-- precedent table chat_rate_windows (also carries user_id, also RLS-enabled
-- with no policy, also server-managed-only).
```

Plus one additive, backward-compatible column on the existing table so status reads can cheaply check the owning job's liveness instead of trusting a stale `'running'` value:

```sql
ALTER TABLE ingest_runs ADD COLUMN job_id uuid REFERENCES jobs(id) ON DELETE SET NULL;
```
Nullable, no backfill needed — every existing row gets `NULL` and is unaffected.

### Enqueue

Same transaction as creating the `IngestRun` row:
```sql
INSERT INTO jobs (job_type, user_id, payload, dedup_key)
VALUES ('gmail_ingest', :user_id, jsonb_build_object('sync_id', :sync_id), 'gmail_ingest:' || :user_id)
ON CONFLICT (dedup_key) WHERE status IN ('queued','claimed','running') DO NOTHING
RETURNING id;
-- if no row returned: a sync is already active for this user -> 409, same UX as today
```
`ingest_runs.job_id` is set to the returned `id` in the same transaction.

### Claim (the worker loop)

```sql
WITH next_job AS (
    SELECT id FROM jobs
    WHERE status = 'queued' AND run_after <= now()
    ORDER BY created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
UPDATE jobs
SET status = 'claimed', claimed_by = :worker_id, claimed_at = now(),
    lease_expires_at = now() + :lease_seconds, attempts = attempts + 1
FROM next_job WHERE jobs.id = next_job.id
RETURNING jobs.*;
```
`lease_seconds` is job-type-specific (gmail_ingest needs the longest lease — minutes; enrichment/distill need seconds). For the long-running gmail_ingest job I'd add a cheap heartbeat (`UPDATE jobs SET lease_expires_at = now() + :lease_seconds WHERE id = :id` every ~30s from inside the running job) rather than pick one static lease long enough to cover the worst case — that keeps crash-detection latency low for the common case without falsely reclaiming a healthy long sync.

### Retry / backoff

On a caught exception in the dispatched function:
```sql
UPDATE jobs
SET status = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'queued' END,
    run_after = now() + (least(power(2, attempts), 60) * interval '1 second'),  -- capped exp backoff
    last_error = :error_type_name,
    claimed_by = NULL, claimed_at = NULL, lease_expires_at = NULL
WHERE id = :id;
```
On success: `status = 'completed', completed_at = now()`.

### Crash recovery (reclaim stale leases)

Run at the top of every claim cycle (cheap, same connection) or on a slower separate tick:
```sql
UPDATE jobs
SET status = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'queued' END,
    claimed_by = NULL, claimed_at = NULL, lease_expires_at = NULL,
    last_error = coalesce(last_error, 'lease_expired')
WHERE status IN ('claimed','running') AND lease_expires_at < now();
```
This is the piece that doesn't exist at all today (§1's core finding: "no third writer").

### Visibility (making `IngestRun.status` truthful again)

When the reclaim sweep flips a job to `'dead'`, it also runs:
```sql
UPDATE ingest_runs SET status = 'error'
WHERE job_id = :job_id AND status = 'running';
```
one extra statement, same transaction. When a job is merely re-queued for retry (not dead), `IngestRun.status` is deliberately left `'running'` — the same logical sync will resume (and, per §1, resuming is cheap/idempotent for gmail_ingest and generation), so nothing is misleading about that state.

### Layering — keeping the P3.3 contracts intact

The generic primitive (`enqueue`/`claim`/`complete`/`fail_and_retry`/`reclaim_stale`) knows only `job_type: str` and `payload: dict` — zero business logic, zero imports from `gmail_closet`/`photo_closet`/`services`. That makes it a legitimate citizen of `app/platform/jobs/`, and it's automatically covered by the existing `platform-depends-on-nothing-upward` contract (a submodule of `app.platform` inherits the contract for free — no new contract needed).

The **registry** (mapping `job_type` string → the actual handler, e.g. `"gmail_ingest": ingest_background`) and the **worker loop** that ties claim→dispatch→complete together *must* import from the feature packages — that's the opposite direction `app.platform` is walled off from. So the registry/loop lives *outside* `app.platform`, in a new top-level module (proposed: `app/worker.py`, sibling to `main.py`) that assembles handlers the same way `main.py` assembles routers today. No wall crossed; no new contract required. (I'll re-run `lint-imports` against the actual code once this is built, but the design as described doesn't introduce any edge the 4 existing contracts forbid.)

---

## 3. Migration plan (0025 → 0026, describe only — nothing applied)

One new revision, `0026_jobs_table`:
1. `CREATE TABLE jobs (...)` as above, with the two indexes + the partial-unique dedup index.
2. `ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;` — no policy (service-only).
3. `ALTER TABLE ingest_runs ADD COLUMN job_id uuid REFERENCES jobs(id) ON DELETE SET NULL;`
4. Corresponding ORM addition: new `app/models/ops.py` (or a new `app/models/jobs.py` — leaning toward a new file since it's a distinct, growing concern, not really "ops" in the `WeatherCache`/`Waitlist` sense) with a `Job` class; `IngestRun.job_id` column added to `app/models/ingestion.py`.
5. Purely additive — no existing column type changes, no data backfill, no `DROP`. `alembic check` should show a clean diff with nothing else disturbed, same verification discipline as every P3.x migration-adjacent phase so far.

Down-migration: drop `ingest_runs.job_id`, drop `jobs`. Safe — nothing else references either by the time this phase's code is reverted (see rollout §4, which never lets the old code path disappear before the new one is proven).

---

## 4. Rollout — cutover without breaking in-flight syncs

1. **Ship the migration alone first.** New table, new column, zero code reads/writes it yet. Inert. Deploy, confirm `alembic check` clean, move on.
2. **Ship the worker process, still inert.** `app/worker.py` polls `jobs`; with nothing enqueuing, it just idles. This is a **new deployable process**, separate from the uvicorn web process(es) — flagging this as an infra decision outside pure code: whatever runs this app today (Render/Fly/systemd/other) needs a second long-running process definition, not just a code change. I don't have visibility into which, so this is a call for you before Phase B.
3. **Feature-flag the cutover, per job type.** `settings.DURABLE_JOBS_ENABLED` (or granular per-type flags), default **false**. False → routes keep calling `background_tasks.add_task(...)` exactly as today, byte-identical behavior. True → the route enqueues a `jobs` row (same transaction as the `IngestRun` insert) instead, and returns immediately; the worker process does the actual work.
4. **Why in-flight syncs are safe across the flip:** the flag is read once, at *dispatch* time, by a *new* incoming request. A sync already running in a Starlette threadpool thread when the flag flips keeps running there, untouched, to completion — the flip only changes what happens to the *next* request. No drain, no dual-write period to reconcile.
5. **Order of cutover** (highest value / lowest residual risk first, per §1's priority read): gmail_ingest → photo generation → enrichment. I'd hold distill_background out of this migration entirely (lowest stakes, has a natural — if currently unscheduled — nightly backstop) and revisit it as a fast-follow once the worker infra is proven, rather than scope-creep Phase B.
6. **Rollback:** flip the flag back to false. New dispatches revert to the old path immediately. Any rows already sitting `'queued'`/`'claimed'` in `jobs` are harmless — either the worker (if still running) finishes them, or they sit idle with no user-facing effect until manually swept. No destructive step required either direction.

---

## 5. R2 reconciliation (in-process locks) — noted, not fixed here

Re-inventoried the 13 `threading.Lock()` sites. Almost all are **correctly** process-local and should stay that way — they're per-run cost budgets (`GenerationBudget`, `VerifyBudget`, `SearchBudget`, `UsageAccumulator`) or per-process caches (`ResolvedImageCache`, the JWKS cache, the collage LRU) whose whole *point* is to reset per run/process. Moving those to a shared store would be a regression, not a fix.

Three are genuine R2 gaps, none of which this phase touches:
- **`app/api/routes/events.py:55`** and **`app/monetization/routes.py:43`** — near-identical per-worker sliding-window rate limiters, both explicitly commented *"not shared across workers/hosts."* The fix direction (when someone picks up R2) is the same pattern chat already uses: `chat_rate_windows`, a Postgres-backed atomic-upsert counter. Not a job-queue concern — flagging only because it's the same underlying "per-worker state doesn't survive/scale" theme as R1.
- **`app/services/stylist/limits.py:186`** (`_local_lock`) — turns out this one is *already* correctly reconciled in production: it's an explicit SQLite-only dev/test fallback; on Postgres the real concurrency cap uses `pg_advisory_lock` (DB-level, already shared). Worth noting as a precedent pattern, not a gap.

None of these three are touched by the `jobs` table design — they're a different problem (request-time rate limiting vs. durable background work) and are called out here only per your instruction to reconcile, not resolve.

---

## 6. Security / PII

- **`jobs.payload`**: ids and small params only — e.g. `{"sync_id": "..."}`, `{"item_ids": [...]}`. Never email content, tokens, or image bytes, matching the discipline already enforced everywhere else in this codebase (fetch_service.py's own docstring: *"Subjects/bodies NEVER logged"*).
- **`jobs.last_error`**: deliberately stricter than the existing log-line convention. Existing code logs `type(exc).__name__` *and* the exception's `str(exc)` in places (e.g. `ingest_background`'s except block) — acceptable for a rotating log with existing access controls, but `jobs.last_error` is a **persisted, directly SQL-queryable column**. Proposing it carry `type(exc).__name__` only, never the exception body, as a tightened bar for this new durable surface.
- **RLS**: `jobs` ships RLS-enabled, no policy (service-only) — consistent with every other server-managed table in this schema (`chat_rate_windows`, `image_blobs`, `product_image_cache`). No new per-user-readable surface is introduced; users still only ever see their own progress via the existing `IngestRun`/status endpoints, unchanged.
- **Commission-blind wall**: unaffected. `jobs` carries no product/payout data and `app.platform.jobs` (§2, layering) never imports `app.ranking`, `app.monetization`, or the composer — the existing contracts cover it with no new rule needed, as reasoned through in §2.

---

## Open questions for you before Phase B

1. **Where does the worker process run?** (second process on the current host/platform, a separate service, a cron-triggered short-lived invocation, etc.) — I don't have visibility into the deployment target.
2. Single generic `DURABLE_JOBS_ENABLED` flag, or per-job-type flags (`GMAIL_INGEST_DURABLE`, `GENERATION_DURABLE`, ...)? I lean per-type, for the staged cutover in §4, but it's slightly more config surface.
3. OK to hold `distill_background` out of the initial migration (§4.5)?
4. `app/worker.py` at the top level (sibling to `main.py`), or under `scripts/`? I lean top-level since it's a real production entrypoint, not a dev tool, but naming/location is cheap to bikeshed now vs. after Phase B is built.
