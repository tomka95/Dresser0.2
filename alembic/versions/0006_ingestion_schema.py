"""gmail->closet ingestion schema foundation (phase 3a)

Revision ID: 0006_ingestion_schema
Revises: 0005_google_accounts_nullable_identity
Create Date: 2026-06-28

Phase 3a of the Gmail->closet ingestion rebuild. Lays the schema foundation the
3b pipeline will write through. Four pieces, all owned by Alembic (no live-only DDL):

  1. clothing_items gains provenance + structured receipt columns, plus the SINGLE
     dedup key UNIQUE(user_id, source_line_key). This one key REPLACES the two
     disagreeing keys of the old (now-deleted) regex pipeline -- the in-memory
     (name, store, price) tuple and the DB (user_id, lower(name), lower(brand))
     lookup -- which together produced both duplicates and data loss. Re-confirming
     the same receipt line can now never insert twice.

  2. processed_messages : per-(user, message) idempotency ledger so a re-run never
     reprocesses an already-seen Gmail message. UNIQUE(user_id, message_id).

  3. ingest_candidates : swipe-review staging. The pipeline writes typed candidates
     here; the user accepts/rejects; only accepted rows become clothing_items.

  4. ingest_runs : per-sync status/progress for the UI (sync_id is the run id).

All three new tables get per-user RLS (auth.uid() = user_id), matching revision
0003. user_id is UUID everywhere, so the policies compare auth.uid() directly --
NO auth.uid()::text cast (that cast is existing user_preferences debt we are not
repeating on new tables).

Conventions reused from the existing migrations:
  * Raw SQL via op.execute; CREATE ... IF NOT EXISTS / guarded ADD CONSTRAINT so
    applying to an already-migrated DB is a no-op.
  * Constraint/index names match the ORM naming convention in app/db.py
    (<table>_<col>_fkey, <table>_<cols>_key, <table>_pkey) so `alembic check`
    stays green against app/models.py.
  * "enum" status columns are text + named CHECK (the user_preferences.source
    pattern), not native PG enums -- autogenerate does not diff CHECK constraints,
    so they never drift, and it avoids enum-type reflection headaches.
  * numeric for money (unit_price / ingest_confidence / confidence_overall);
    3-char currency guarded by length(currency)=3 (length() is portable to the
    SQLite dev/test dialect; char_length() is not).

Postgres/Supabase-specific (uuid, jsonb, gen_random_uuid(), RLS) by design. The
optional LOCAL_DB=sqlite dev/test mode never runs Alembic migrations.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0006_ingestion_schema"
down_revision = "0005_google_accounts_nullable_identity"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
-- ============================================================================
-- (1) clothing_items: provenance + structured receipt fields + single dedup key
-- ============================================================================
ALTER TABLE public.clothing_items
    ADD COLUMN IF NOT EXISTS source_message_id        text,
    ADD COLUMN IF NOT EXISTS source_google_account_id bigint,
    ADD COLUMN IF NOT EXISTS source_line_key          text,
    ADD COLUMN IF NOT EXISTS order_id                 text,
    ADD COLUMN IF NOT EXISTS order_date               date,
    ADD COLUMN IF NOT EXISTS unit_price               numeric,
    ADD COLUMN IF NOT EXISTS currency                 text,
    ADD COLUMN IF NOT EXISTS quantity                 integer NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS is_return                boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS ingest_confidence        numeric;

-- FK to the per-user Gmail token row that sourced this item. ON DELETE SET NULL:
-- disconnecting Gmail (deleting the google_accounts row) must NOT delete the
-- user's already-imported closet items, only sever the provenance link.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'public'
          AND table_name = 'clothing_items'
          AND constraint_name = 'clothing_items_source_google_account_id_fkey'
    ) THEN
        ALTER TABLE public.clothing_items
            ADD CONSTRAINT clothing_items_source_google_account_id_fkey
            FOREIGN KEY (source_google_account_id)
            REFERENCES public.google_accounts(id) ON DELETE SET NULL;
    END IF;
END $$;

-- 3-char ISO-4217 currency guard (named CHECK; not diffed by autogenerate).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'public'
          AND table_name = 'clothing_items'
          AND constraint_name = 'clothing_items_currency_check'
    ) THEN
        ALTER TABLE public.clothing_items
            ADD CONSTRAINT clothing_items_currency_check
            CHECK (currency IS NULL OR length(currency) = 3);
    END IF;
END $$;

-- THE single dedup key. Existing rows have source_line_key NULL; Postgres treats
-- NULLs as distinct, so adding this UNIQUE never collides with legacy data.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'public'
          AND table_name = 'clothing_items'
          AND constraint_name = 'clothing_items_user_id_source_line_key_key'
    ) THEN
        ALTER TABLE public.clothing_items
            ADD CONSTRAINT clothing_items_user_id_source_line_key_key
            UNIQUE (user_id, source_line_key);
    END IF;
END $$;

-- ============================================================================
-- (2) processed_messages: per-(user, message) idempotency ledger
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.processed_messages (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    google_account_id bigint,
    message_id        text NOT NULL,
    content_hash      text,
    status            text NOT NULL DEFAULT 'fetched'
                          CHECK (status IN ('fetched','filtered_out','extracted','confirmed','rejected','error')),
    processed_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT processed_messages_user_id_message_id_key UNIQUE (user_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_processed_messages_user_id
    ON public.processed_messages USING btree (user_id);

-- ============================================================================
-- (3) ingest_candidates: swipe-review staging (typed, pre-closet)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.ingest_candidates (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    sync_id            uuid,
    message_id         text,
    name               text,
    brand              text,
    category           text,
    color              text,
    size               text,
    quantity           integer NOT NULL DEFAULT 1,
    unit_price         numeric,
    currency           text,
    order_date         date,
    is_return          boolean NOT NULL DEFAULT false,
    merchant           text,
    order_id           text,
    image_url          text,
    confidence_overall numeric,
    confidence_json    jsonb,
    status             text NOT NULL DEFAULT 'pending'
                           CHECK (status IN ('pending','accepted','rejected')),
    created_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ingest_candidates_currency_check CHECK (currency IS NULL OR length(currency) = 3)
);
CREATE INDEX IF NOT EXISTS idx_ingest_candidates_user_id
    ON public.ingest_candidates USING btree (user_id);
CREATE INDEX IF NOT EXISTS idx_ingest_candidates_sync_id
    ON public.ingest_candidates USING btree (sync_id);
CREATE INDEX IF NOT EXISTS idx_ingest_candidates_user_status
    ON public.ingest_candidates USING btree (user_id, status);

-- ============================================================================
-- (4) ingest_runs: per-sync status/progress (sync_id is the run identifier)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.ingest_runs (
    sync_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    status          text NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running','completed','error')),
    fetched_count   integer NOT NULL DEFAULT 0,
    filtered_count  integer NOT NULL DEFAULT 0,
    extracted_count integer NOT NULL DEFAULT 0,
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz
);
CREATE INDEX IF NOT EXISTS idx_ingest_runs_user_id
    ON public.ingest_runs USING btree (user_id);

-- ============================================================================
-- Per-user RLS on the three new tables (guarded: requires Supabase auth schema).
-- user_id is UUID -> compare auth.uid() directly, no ::text cast.
-- ============================================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) THEN
        RAISE NOTICE 'auth.users absent; skipping per-user RLS (non-Supabase DB).';
        RETURN;
    END IF;

    -- processed_messages -----------------------------------------------------
    EXECUTE 'ALTER TABLE public.processed_messages ENABLE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS processed_messages_select_own ON public.processed_messages';
    EXECUTE 'CREATE POLICY processed_messages_select_own ON public.processed_messages
             FOR SELECT USING (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS processed_messages_insert_own ON public.processed_messages';
    EXECUTE 'CREATE POLICY processed_messages_insert_own ON public.processed_messages
             FOR INSERT WITH CHECK (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS processed_messages_update_own ON public.processed_messages';
    EXECUTE 'CREATE POLICY processed_messages_update_own ON public.processed_messages
             FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS processed_messages_delete_own ON public.processed_messages';
    EXECUTE 'CREATE POLICY processed_messages_delete_own ON public.processed_messages
             FOR DELETE USING (auth.uid() = user_id)';

    -- ingest_candidates ------------------------------------------------------
    EXECUTE 'ALTER TABLE public.ingest_candidates ENABLE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS ingest_candidates_select_own ON public.ingest_candidates';
    EXECUTE 'CREATE POLICY ingest_candidates_select_own ON public.ingest_candidates
             FOR SELECT USING (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS ingest_candidates_insert_own ON public.ingest_candidates';
    EXECUTE 'CREATE POLICY ingest_candidates_insert_own ON public.ingest_candidates
             FOR INSERT WITH CHECK (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS ingest_candidates_update_own ON public.ingest_candidates';
    EXECUTE 'CREATE POLICY ingest_candidates_update_own ON public.ingest_candidates
             FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS ingest_candidates_delete_own ON public.ingest_candidates';
    EXECUTE 'CREATE POLICY ingest_candidates_delete_own ON public.ingest_candidates
             FOR DELETE USING (auth.uid() = user_id)';

    -- ingest_runs ------------------------------------------------------------
    EXECUTE 'ALTER TABLE public.ingest_runs ENABLE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS ingest_runs_select_own ON public.ingest_runs';
    EXECUTE 'CREATE POLICY ingest_runs_select_own ON public.ingest_runs
             FOR SELECT USING (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS ingest_runs_insert_own ON public.ingest_runs';
    EXECUTE 'CREATE POLICY ingest_runs_insert_own ON public.ingest_runs
             FOR INSERT WITH CHECK (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS ingest_runs_update_own ON public.ingest_runs';
    EXECUTE 'CREATE POLICY ingest_runs_update_own ON public.ingest_runs
             FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS ingest_runs_delete_own ON public.ingest_runs';
    EXECUTE 'CREATE POLICY ingest_runs_delete_own ON public.ingest_runs
             FOR DELETE USING (auth.uid() = user_id)';
END $$;
"""


DOWNGRADE_SQL = r"""
-- Drop the three new tables (DROP TABLE removes their RLS policies + indexes). --
DROP TABLE IF EXISTS public.ingest_candidates;
DROP TABLE IF EXISTS public.ingest_runs;
DROP TABLE IF EXISTS public.processed_messages;

-- Revert clothing_items additions (constraints first, then columns). ----------
ALTER TABLE public.clothing_items
    DROP CONSTRAINT IF EXISTS clothing_items_user_id_source_line_key_key,
    DROP CONSTRAINT IF EXISTS clothing_items_source_google_account_id_fkey,
    DROP CONSTRAINT IF EXISTS clothing_items_currency_check;

ALTER TABLE public.clothing_items
    DROP COLUMN IF EXISTS source_message_id,
    DROP COLUMN IF EXISTS source_google_account_id,
    DROP COLUMN IF EXISTS source_line_key,
    DROP COLUMN IF EXISTS order_id,
    DROP COLUMN IF EXISTS order_date,
    DROP COLUMN IF EXISTS unit_price,
    DROP COLUMN IF EXISTS currency,
    DROP COLUMN IF EXISTS quantity,
    DROP COLUMN IF EXISTS is_return,
    DROP COLUMN IF EXISTS ingest_confidence;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
