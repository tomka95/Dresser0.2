"""todays_look: half-daily cache of the user's composed Today's Look

Revision ID: 0029_todays_look
Revises: 0028_photo_usage
Create Date: 2026-07-08

Additive, backward-compatible. Ships ONE table: `todays_look`, a per-user cache
(one row per user) of the composed daily outfit so Home stops recomposing +
re-rendering the grid collage on every visit. GET returns the stored payload
verbatim while the `factor_signature` still matches the live factors AND we're in
the same half-day bucket; any factor change (warmth band / derived occasion /
closet count+mtime) or a new half-day forces a fresh compose. Remix overwrites.

Stores only DERIVED context (a warmth band int, a coarse occasion string) and the
already-public outfit payload (item ids + attributes + collage URL). NO raw
calendar event titles are stored (the composer only ever receives a derived
occasion/formality; titles never reach this layer).

SECURITY posture (mirrors calendar_accounts / 0027):
  * Per-user RLS (auth.uid() = user_id), 4-verb (SELECT/INSERT/UPDATE/DELETE).
  * ON DELETE CASCADE on user_id: deleting a user wipes their cached look.
  * EXPLICIT GRANT to the `authenticated` role — REQUIRED: RLS restricts WHICH
    rows a role sees but does NOT grant table access, and GET/remix read+write
    this row on the RLS-scoped route connection (SET LOCAL role authenticated).
    uuid PK (gen_random_uuid()) means there is NO sequence to grant.

Conventions reused from 0027: raw SQL via op.execute; CREATE TABLE IF NOT EXISTS
with inline PK/UNIQUE/REFERENCES so Postgres auto-names them to match the ORM
naming convention (todays_look_pkey, todays_look_user_id_key,
todays_look_user_id_fkey); RLS + GRANT guarded on the Supabase auth schema so a
non-Supabase / SQLite dev DB is a clean no-op. `alembic check` clean after upgrade
(the ORM models this table 1:1).
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0029_todays_look"
down_revision = "0028_photo_usage"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
-- ============================================================================
-- todays_look: per-user half-daily cache of the composed Today's Look.
--   uuid PK (gen_random_uuid) => no sequence to grant. One row per user.
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.todays_look (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          uuid NOT NULL UNIQUE REFERENCES public.users(id) ON DELETE CASCADE,
    factor_signature text NOT NULL,
    outfit_json      jsonb NOT NULL,
    collage_url      text,
    title            text,
    caption          text,
    warmth           integer,
    occasion         text,
    half_day_bucket  text NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now()
);

-- ============================================================================
-- RLS (auth.uid() = user_id, 4-verb) + EXPLICIT GRANT to authenticated.
-- Guarded on the Supabase auth schema so non-Supabase DBs skip cleanly.
-- ============================================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) THEN
        RAISE NOTICE 'auth.users absent; skipping RLS/GRANT on todays_look (non-Supabase DB).';
        RETURN;
    END IF;

    -- RLS alone does not grant table access; the RLS-scoped route (role
    -- authenticated) both reads (GET cache hit) and writes (compose/remix upsert)
    -- this row, so it needs all four verbs. No sequence (uuid PK) => no seq grant.
    EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON public.todays_look TO authenticated';

    EXECUTE 'ALTER TABLE public.todays_look ENABLE ROW LEVEL SECURITY';

    EXECUTE 'DROP POLICY IF EXISTS todays_look_select_own ON public.todays_look';
    EXECUTE 'CREATE POLICY todays_look_select_own ON public.todays_look
             FOR SELECT USING (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS todays_look_insert_own ON public.todays_look';
    EXECUTE 'CREATE POLICY todays_look_insert_own ON public.todays_look
             FOR INSERT WITH CHECK (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS todays_look_update_own ON public.todays_look';
    EXECUTE 'CREATE POLICY todays_look_update_own ON public.todays_look
             FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS todays_look_delete_own ON public.todays_look';
    EXECUTE 'CREATE POLICY todays_look_delete_own ON public.todays_look
             FOR DELETE USING (auth.uid() = user_id)';
END $$;
"""


DOWNGRADE_SQL = r"""
-- DROP TABLE removes the table's RLS policies; grants vanish with it.
DROP TABLE IF EXISTS public.todays_look;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
