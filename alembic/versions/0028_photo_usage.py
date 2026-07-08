"""photo_usage — per-user per-month photo-quota ledger (SCRUM-44 counter).

The free tier is "30 photos a month". Server-side ENFORCEMENT (SCRUM-44) is not built
yet, but the counter it will read needs to exist and be wired now so a Regenerate (and,
later, an ingest commit) durably records consumption. This table is the monthly analogue
of chat_usage (migration 0020): one row per (user, month), atomically upserted.

Per-user RLS (auth.uid() = user_id, all four verbs) mirrors the chat_usage posture; the
guard skips RLS on a non-Supabase DB (no auth.users). Nothing but counts is stored.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "0028_photo_usage"
down_revision = "0027_calendar_accounts"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
CREATE TABLE IF NOT EXISTS public.photo_usage (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    period_start  date NOT NULL,
    photos_used   integer NOT NULL DEFAULT 0,
    regenerations integer NOT NULL DEFAULT 0,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT photo_usage_user_id_period_start_key UNIQUE (user_id, period_start)
);

CREATE INDEX IF NOT EXISTS idx_photo_usage_user_id
    ON public.photo_usage USING btree (user_id);

-- Per-user RLS (0020 pattern: guarded, all four verbs, auth.uid() = user_id).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) THEN
        RAISE NOTICE 'auth.users absent; skipping per-user RLS (non-Supabase DB).';
        RETURN;
    END IF;

    EXECUTE 'ALTER TABLE public.photo_usage ENABLE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS photo_usage_select_own ON public.photo_usage';
    EXECUTE 'CREATE POLICY photo_usage_select_own ON public.photo_usage FOR SELECT USING (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS photo_usage_insert_own ON public.photo_usage';
    EXECUTE 'CREATE POLICY photo_usage_insert_own ON public.photo_usage FOR INSERT WITH CHECK (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS photo_usage_update_own ON public.photo_usage';
    EXECUTE 'CREATE POLICY photo_usage_update_own ON public.photo_usage FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS photo_usage_delete_own ON public.photo_usage';
    EXECUTE 'CREATE POLICY photo_usage_delete_own ON public.photo_usage FOR DELETE USING (auth.uid() = user_id)';
END $$;
"""


DOWNGRADE_SQL = r"""
DROP TABLE IF EXISTS public.photo_usage;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
