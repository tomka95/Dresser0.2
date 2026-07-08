"""jobs: durable job queue + ingest_runs.job_id (P3.8, ARCHITECTURE_AUDIT R1, Wave 1)

Revision ID: 0026_jobs_table
Revises: 0025_weather_cache_comments
Create Date: 2026-07-08

Additive, backward-compatible, INERT until a per-type feature flag is flipped
(all default OFF). Ships two things:

  jobs : the Postgres-native durable queue (claimed via FOR UPDATE SKIP LOCKED,
    reclaimed after a crash by a stale-lock sweep). SERVICE-ONLY -- RLS enabled
    with NO policy (deny-all for anon/authenticated), the chat_rate_windows /
    image_blobs posture: no user-facing route ever touches a job row, the worker
    manages it on the owner connection. Carries user_id for ON DELETE CASCADE +
    per-user observability only. payload/last_error carry ids + exception TYPE
    names only, never tokens/PII/bodies (see app/models/jobs.py).

  ingest_runs.job_id : nullable FK to jobs(id) ON DELETE SET NULL. Lets the
    reclaim sweep flip a run stuck 'running' (crashed worker) to 'error' so
    GET /gmail/ingest/status stops lying. Every existing row gets NULL, unaffected.

Conventions reused from 0020/0024: raw SQL via op.execute; CREATE TABLE IF NOT
EXISTS; inline PK/REFERENCES so Postgres auto-names them to match the ORM naming
convention (jobs_pkey, jobs_user_id_fkey, ingest_runs_job_id_fkey); RLS guarded
on the Supabase auth schema.

Postgres/Supabase-specific. LOCAL_DB=sqlite dev/test never runs Alembic
(create_all; RLS skipped). Purely additive: no column-type change, no backfill,
no DROP. `alembic check` clean after upgrade.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0026_jobs_table"
down_revision = "0025_weather_cache_comments"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
-- ============================================================================
-- jobs: durable background-work queue. queued -> running -> succeeded|failed.
--   Claimed with FOR UPDATE SKIP LOCKED; stale 'running' rows (dead worker) are
--   reclaimed via locked_at age. SERVICE-ONLY (RLS, no policy).
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.jobs (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    type          text NOT NULL,
    user_id       uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    payload       jsonb NOT NULL DEFAULT '{}'::jsonb,
    status        text NOT NULL DEFAULT 'queued',
    attempts      integer NOT NULL DEFAULT 0,
    max_attempts  integer NOT NULL DEFAULT 3,
    run_after     timestamptz NOT NULL DEFAULT now(),
    locked_at     timestamptz,
    locked_by     text,
    last_error    text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT jobs_status_check
        CHECK (status IN ('queued','running','succeeded','failed'))
);
-- The claim query: WHERE status='queued' AND run_after <= now() ORDER BY
-- created_at LIMIT 1 FOR UPDATE SKIP LOCKED. Leading status keeps it a range scan.
CREATE INDEX IF NOT EXISTS idx_jobs_claim
    ON public.jobs USING btree (status, run_after);
-- Per-user lookups / CASCADE support.
CREATE INDEX IF NOT EXISTS idx_jobs_user_id
    ON public.jobs USING btree (user_id);

-- Truthful run status after a crash: link the run to its owning job.
ALTER TABLE public.ingest_runs
    ADD COLUMN IF NOT EXISTS job_id uuid REFERENCES public.jobs(id) ON DELETE SET NULL;

-- ============================================================================
-- RLS: service-only. Enable RLS with NO policy -> deny-all for anon/authenticated
-- (the worker reads/writes jobs on the owner connection). Guarded on Supabase auth.
-- Mirrors chat_rate_windows (0020) / product_image_cache (0010).
-- ============================================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) THEN
        RAISE NOTICE 'auth.users absent; skipping RLS on jobs (non-Supabase DB).';
        RETURN;
    END IF;

    EXECUTE 'ALTER TABLE public.jobs ENABLE ROW LEVEL SECURITY';
END $$;
"""


DOWNGRADE_SQL = r"""
ALTER TABLE public.ingest_runs DROP COLUMN IF EXISTS job_id;
DROP INDEX IF EXISTS public.idx_jobs_user_id;
DROP INDEX IF EXISTS public.idx_jobs_claim;
DROP TABLE IF EXISTS public.jobs;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
