"""generation_attempts counter on ingest_candidates + clothing_items (self-heal ceiling)

Revision ID: 0034_generation_attempts
Revises: 0033_backfill_on_model
Create Date: 2026-07-09

Additive, backward-compatible. One integer `generation_attempts` (NOT NULL DEFAULT 0) on
both ingest_candidates and clothing_items.

Cost cut #2 (self-heal attempt ceiling): a photo generation target whose generate->verify
keeps missing was left 'pending_retry' forever and re-generated + re-verified by every
self-heal sweep — permanent re-billing. This column counts FAILED generate->verify
attempts; after settings.GENERATION_MAX_ATTEMPTS (default 3) the target goes terminal
(generation_status='failed'), which every target query already excludes. Transient misses
(download error / budget / provider unavailable) do NOT increment it, so genuinely
transient items keep retrying.

No CHECK / no RLS change (both tables are already per-user). ADD COLUMN IF NOT EXISTS keeps
re-runs safe. Existing rows backfill to 0 via the server default (attempts start fresh).
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0034_generation_attempts"
down_revision = "0033_backfill_on_model"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
ALTER TABLE public.ingest_candidates ADD COLUMN IF NOT EXISTS generation_attempts integer NOT NULL DEFAULT 0;
ALTER TABLE public.clothing_items    ADD COLUMN IF NOT EXISTS generation_attempts integer NOT NULL DEFAULT 0;
"""

DOWNGRADE_SQL = r"""
ALTER TABLE public.clothing_items    DROP COLUMN IF EXISTS generation_attempts;
ALTER TABLE public.ingest_candidates DROP COLUMN IF EXISTS generation_attempts;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
