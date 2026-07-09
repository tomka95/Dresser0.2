"""ingest_runs: trigger + review-banner show-once timestamps (Wave C / Fix 1)

Revision ID: 0031_ingest_runs_trigger_review
Revises: 0030_clothing_items_category_not_null
Create Date: 2026-07-08

Additive, backward-compatible. Three nullable columns on ingest_runs:
  * trigger              — 'onboarding' (the Gmail-connect auto-scan) | 'manual' (the
                           explicit "Scan my inbox" CTA). NULL for every pre-0031 run.
  * review_surfaced_at   — stamped when the user OPENS the Home "review N ready" banner.
  * review_dismissed_at  — stamped when the user DISMISSES it.
GET /gmail/ingest/pending-review surfaces a completed run only while BOTH review_* are
NULL, so the banner shows once and never nags.

RLS is UNCHANGED — ingest_runs is already per-user (RLS + the explicit user_id filter on
every query). No new grants/policies. The CHECK on trigger is a named constraint (the ORM
carries the same one; named CHECKs are not diffed by autogenerate, so `alembic check` is
clean after upgrade). Postgres-targeted (the dev/test SQLite DB gets these from the ORM
model via create_all); ADD COLUMN IF NOT EXISTS + a guarded ADD CONSTRAINT make re-runs
safe.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0031_ingest_runs_trigger_review"
down_revision = "0030_clothing_items_category_not_null"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
ALTER TABLE public.ingest_runs ADD COLUMN IF NOT EXISTS "trigger" text;
ALTER TABLE public.ingest_runs ADD COLUMN IF NOT EXISTS review_surfaced_at timestamptz;
ALTER TABLE public.ingest_runs ADD COLUMN IF NOT EXISTS review_dismissed_at timestamptz;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ingest_runs_trigger'
    ) THEN
        ALTER TABLE public.ingest_runs
            ADD CONSTRAINT ingest_runs_trigger
            CHECK ("trigger" IS NULL OR "trigger" IN ('onboarding','manual'));
    END IF;
END $$;
"""


DOWNGRADE_SQL = r"""
ALTER TABLE public.ingest_runs DROP CONSTRAINT IF EXISTS ingest_runs_trigger;
ALTER TABLE public.ingest_runs DROP COLUMN IF EXISTS review_dismissed_at;
ALTER TABLE public.ingest_runs DROP COLUMN IF EXISTS review_surfaced_at;
ALTER TABLE public.ingest_runs DROP COLUMN IF EXISTS "trigger";
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
