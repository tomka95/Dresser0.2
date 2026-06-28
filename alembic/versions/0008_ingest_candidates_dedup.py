"""ingest_candidates: content-key staging dedup (phase 3c tuning)

Revision ID: 0008_ingest_candidates_dedup
Revises: 0007_ingest_runs_total_estimate
Create Date: 2026-06-28

The 3c extractor staged the SAME owned item twice when it appeared in two emails
(the order-confirmation + shipping-confirmation pattern), because the per-line key
included message_id. This adds a CONTENT-based dedup key so one owned item becomes
one candidate regardless of how many emails mention it.

Three additions to ingest_candidates:
  * source_line_key   : content key = hash(normalized_name + size + color + unit_price).
                        Same item across emails -> same key. UNIQUE(user_id,
                        source_line_key) lets the staging writer ON CONFLICT DO
                        UPDATE (fill-nulls / keep-richest) instead of inserting a
                        duplicate row. (This is the SAME column name 3d copies onto
                        clothing_items.source_line_key at confirm time, so the dedup
                        carries through to the closet.)
  * source_message_ids: text[] of every Gmail message that contributed this item, so
                        collapsing emails never loses a source link.
  * seen_count        : how many distinct source emails contributed (>=1).

3b's per-(user, message) idempotency in processed_messages is untouched. RLS on
ingest_candidates (migration 0006) already covers the new columns.

Postgres/Supabase-specific (text[], guarded ADD CONSTRAINT). The optional
LOCAL_DB=sqlite dev/test mode never runs Alembic migrations.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0008_ingest_candidates_dedup"
down_revision = "0007_ingest_runs_total_estimate"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
ALTER TABLE public.ingest_candidates
    ADD COLUMN IF NOT EXISTS source_line_key    text,
    ADD COLUMN IF NOT EXISTS source_message_ids text[] NOT NULL DEFAULT '{}'::text[],
    ADD COLUMN IF NOT EXISTS seen_count         integer NOT NULL DEFAULT 1;

-- Content-key dedup: same owned item collapses to one candidate per user. Existing
-- rows have source_line_key NULL; Postgres treats NULLs as distinct, so adding this
-- UNIQUE never collides with already-staged (pre-dedup) candidates.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'public'
          AND table_name = 'ingest_candidates'
          AND constraint_name = 'ingest_candidates_user_id_source_line_key_key'
    ) THEN
        ALTER TABLE public.ingest_candidates
            ADD CONSTRAINT ingest_candidates_user_id_source_line_key_key
            UNIQUE (user_id, source_line_key);
    END IF;
END $$;
"""


DOWNGRADE_SQL = r"""
ALTER TABLE public.ingest_candidates
    DROP CONSTRAINT IF EXISTS ingest_candidates_user_id_source_line_key_key;

ALTER TABLE public.ingest_candidates
    DROP COLUMN IF EXISTS source_line_key,
    DROP COLUMN IF EXISTS source_message_ids,
    DROP COLUMN IF EXISTS seen_count;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
