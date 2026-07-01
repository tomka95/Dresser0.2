"""photo ingest: source_type provenance + processed_uploads idempotency (Wave 1)

Revision ID: 0014_photo_ingest
Revises: 0013_processed_messages_extract_priority
Create Date: 2026-06-29

Wave 1 adds a SECOND ingestion source — a user-uploaded photo whose garments are
detected, cut out, and staged as the SAME ingest_candidates the Gmail pipeline uses,
then confirmed through the SAME review_service path. This migration lays the schema
that lets the shared spine tell the two sources apart and keeps photo uploads
idempotent. Two pieces, both owned by Alembic (no live-only DDL):

  1. source_type provenance on the three shared tables — clothing_items,
     ingest_candidates, ingest_runs. text NOT NULL DEFAULT 'gmail' so every existing
     row backfills to 'gmail' (the only source until now); the photo pipeline writes
     'photo'. Named CHECK source_type IN ('gmail','photo') on each (the
     user_preferences.source pattern — autogenerate does not diff CHECKs, so they
     never drift). confirm copies the candidate's value onto the closet row.

  2. processed_uploads : per-(user, image) idempotency ledger — the photo analogue of
     processed_messages. UNIQUE(user_id, image_sha256) makes re-uploading the same
     file a no-op; phash enables near-duplicate skipping. Per-user RLS (auth.uid() =
     user_id), exactly matching the 0006 ingestion tables.

Conventions reused from 0006/0008/0010/0011: raw SQL via op.execute; ADD COLUMN /
CREATE TABLE IF NOT EXISTS + guarded ADD CONSTRAINT so re-applying is a no-op;
constraint/index names match the ORM naming convention in app/db.py so `alembic check`
stays green against app/models.py.

Postgres/Supabase-specific (uuid, gen_random_uuid(), RLS) by design. The optional
LOCAL_DB=sqlite dev/test mode never runs Alembic migrations.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0014_photo_ingest"
down_revision = "0013_processed_messages_extract_priority"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
-- ============================================================================
-- (1) source_type provenance on the three shared ingestion tables.
--     text NOT NULL DEFAULT 'gmail' backfills every existing row in one shot.
-- ============================================================================
ALTER TABLE public.clothing_items
    ADD COLUMN IF NOT EXISTS source_type text NOT NULL DEFAULT 'gmail';
ALTER TABLE public.ingest_candidates
    ADD COLUMN IF NOT EXISTS source_type text NOT NULL DEFAULT 'gmail';
ALTER TABLE public.ingest_runs
    ADD COLUMN IF NOT EXISTS source_type text NOT NULL DEFAULT 'gmail';

-- Named CHECK source_type IN ('gmail','photo') on each (guarded; idempotent).
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['clothing_items','ingest_candidates','ingest_runs'] LOOP
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.table_constraints
            WHERE table_schema = 'public'
              AND table_name = t
              AND constraint_name = t || '_source_type_check'
        ) THEN
            EXECUTE format(
                'ALTER TABLE public.%I ADD CONSTRAINT %I '
                'CHECK (source_type IN (''gmail'',''photo''))',
                t, t || '_source_type_check'
            );
        END IF;
    END LOOP;
END $$;

-- ============================================================================
-- (2) processed_uploads: per-(user, image) idempotency ledger for photo ingest.
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.processed_uploads (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    sync_id       uuid,
    image_sha256  text NOT NULL,
    phash         text,
    status        text NOT NULL DEFAULT 'processed'
                      CHECK (status IN ('processed','held_multi_person','error')),
    item_count    integer NOT NULL DEFAULT 0,
    processed_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT processed_uploads_user_id_image_sha256_key UNIQUE (user_id, image_sha256)
);
CREATE INDEX IF NOT EXISTS idx_processed_uploads_user_id
    ON public.processed_uploads USING btree (user_id);
CREATE INDEX IF NOT EXISTS idx_processed_uploads_user_phash
    ON public.processed_uploads USING btree (user_id, phash);

-- Per-user RLS (guarded: requires the Supabase auth schema). user_id is UUID ->
-- compare auth.uid() directly, no ::text cast (matches the 0006 tables).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) THEN
        RAISE NOTICE 'auth.users absent; skipping per-user RLS (non-Supabase DB).';
        RETURN;
    END IF;

    EXECUTE 'ALTER TABLE public.processed_uploads ENABLE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS processed_uploads_select_own ON public.processed_uploads';
    EXECUTE 'CREATE POLICY processed_uploads_select_own ON public.processed_uploads
             FOR SELECT USING (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS processed_uploads_insert_own ON public.processed_uploads';
    EXECUTE 'CREATE POLICY processed_uploads_insert_own ON public.processed_uploads
             FOR INSERT WITH CHECK (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS processed_uploads_update_own ON public.processed_uploads';
    EXECUTE 'CREATE POLICY processed_uploads_update_own ON public.processed_uploads
             FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS processed_uploads_delete_own ON public.processed_uploads';
    EXECUTE 'CREATE POLICY processed_uploads_delete_own ON public.processed_uploads
             FOR DELETE USING (auth.uid() = user_id)';
END $$;
"""


DOWNGRADE_SQL = r"""
DROP TABLE IF EXISTS public.processed_uploads;

ALTER TABLE public.ingest_runs       DROP CONSTRAINT IF EXISTS ingest_runs_source_type_check;
ALTER TABLE public.ingest_candidates DROP CONSTRAINT IF EXISTS ingest_candidates_source_type_check;
ALTER TABLE public.clothing_items    DROP CONSTRAINT IF EXISTS clothing_items_source_type_check;

ALTER TABLE public.ingest_runs       DROP COLUMN IF EXISTS source_type;
ALTER TABLE public.ingest_candidates DROP COLUMN IF EXISTS source_type;
ALTER TABLE public.clothing_items    DROP COLUMN IF EXISTS source_type;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
