"""ingest_runs cost columns: per-sync Gemini + Serper usage and dollars

Revision ID: 0012_ingest_runs_cost
Revises: 0011_ingest_candidates_image_status
Create Date: 2026-06-28

Per-sync cost tracking. Every sync's REAL provider usage (recorded, never estimated —
see app/gmail_closet/usage.py) is attributed to its ingest_run, broken out by tier so
we can see which one drives cost:

  * gemini_input_tokens / gemini_output_tokens : EXTRACTION (base Flash-Lite + Flash
    escalation) token counts from each call's usage_metadata, summed per sync.
  * verify_input_tokens / verify_output_tokens : VISION-VERIFY (Flash-Lite) token
    counts, accumulated in the background image-fill pass.
  * serper_credits : one credit per ISSUED Serper shopping-search query.
  * extract_cost_usd / verify_cost_usd / search_cost_usd : per-tier dollars, computed
    from the recorded units × the editable per-unit rates in config.
  * cost_usd : the per-sync total (= extract + verify + search).

Privacy: counts + dollars ONLY — never any email content. All NOT NULL DEFAULT 0 so
existing runs read as zero-cost and the app never has to null-check.

Conventions reused from 0006-0011: raw SQL via op.execute; ADD COLUMN IF NOT EXISTS so
re-applying is a no-op. No constraints/indexes added, so nothing to name. Column types
(bigint / integer / numeric) mirror the ORM (IngestRun) so `alembic check` stays green;
server defaults live here (compare_server_default is off in env.py).

Postgres/Supabase-specific. The optional LOCAL_DB=sqlite dev/test mode never runs
Alembic migrations.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0012_ingest_runs_cost"
down_revision = "0011_ingest_candidates_image_status"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
ALTER TABLE public.ingest_runs
    ADD COLUMN IF NOT EXISTS gemini_input_tokens  bigint  NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS gemini_output_tokens bigint  NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS verify_input_tokens  bigint  NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS verify_output_tokens bigint  NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS serper_credits       integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS extract_cost_usd     numeric NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS verify_cost_usd      numeric NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS search_cost_usd      numeric NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS cost_usd             numeric NOT NULL DEFAULT 0;
"""


DOWNGRADE_SQL = r"""
ALTER TABLE public.ingest_runs
    DROP COLUMN IF EXISTS gemini_input_tokens,
    DROP COLUMN IF EXISTS gemini_output_tokens,
    DROP COLUMN IF EXISTS verify_input_tokens,
    DROP COLUMN IF EXISTS verify_output_tokens,
    DROP COLUMN IF EXISTS serper_credits,
    DROP COLUMN IF EXISTS extract_cost_usd,
    DROP COLUMN IF EXISTS verify_cost_usd,
    DROP COLUMN IF EXISTS search_cost_usd,
    DROP COLUMN IF EXISTS cost_usd;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
