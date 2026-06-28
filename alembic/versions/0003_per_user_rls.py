"""per-user RLS policies + security hardening (capture live out-of-band state)

Revision ID: 0003_per_user_rls
Revises: 0002_users_auth_fk
Create Date: 2026-06-28

Phase 1 of the Supabase Auth cutover applied per-user Row Level Security and a few
small security fixes to the LIVE database out-of-band (via the Supabase dashboard
/ MCP). This migration captures that exact state in Alembic so migrations remain
the single source of truth. It is a faithful, idempotent snapshot of what is
already live -- applying it to the live DB is a no-op; applying it to a fresh DB
reproduces the same security posture.

What it reproduces (verified against the live DB):

1. Per-user RLS on six tables (RLS enabled + PERMISSIVE policies for role PUBLIC):
     * public.users                 SELECT, UPDATE        (auth.uid() = id)
     * public.clothing_items        SELECT/INSERT/UPDATE/DELETE  (auth.uid() = user_id)
     * public.item_images           SELECT/INSERT/UPDATE/DELETE  scoped via EXISTS on
                                     the parent clothing_items.user_id = auth.uid()
     * public.google_accounts       SELECT/INSERT/UPDATE/DELETE  (auth.uid() = user_id)
     * public.user_preferences      SELECT/INSERT/UPDATE/DELETE  (auth.uid()::text = user_id)
     * public.user_preference_events SELECT/INSERT/UPDATE/DELETE (auth.uid()::text = user_id)
   user_preferences(.events).user_id is TEXT, hence the ::text cast on auth.uid()
   (a UUID). The two read-only tables (users) intentionally have only SELECT/UPDATE
   policies -- profiles are created by the backend (service role, which bypasses
   RLS) and never deleted by the user.

2. Lock-down RLS (enabled, NO policies) on three non-user tables, so they are not
   reachable via the anon/authenticated PostgREST roles:
     * public.alembic_version   * public.waitlist   * public.weather_cache
   Enabling RLS on alembic_version is safe: the migration runs as the table owner,
   which BYPASSES RLS, so Alembic can still read/write its version row.

3. Pin the trigger function's search_path to '' (mutable-search_path hardening):
     ALTER FUNCTION public.update_user_preferences_updated_at() SET search_path = ''
   NOTE: that function (and its trigger) were themselves created out-of-band and
   are not yet in any migration, so this ALTER is existence-guarded -- on a fresh
   DB built purely from migrations it is a no-op until the function creation is
   captured (tracked as separate follow-up drift; invisible to `alembic check`,
   which does not diff functions/triggers).

Idempotency / guards:
  * Per-user policies are wrapped in a guard that skips entirely when the Supabase
    `auth` schema is absent (e.g. plain local Postgres), matching revision 0002.
  * Each policy is (DROP POLICY IF EXISTS -> CREATE POLICY); ENABLE ROW LEVEL
    SECURITY is inherently idempotent. Safe to re-run on the already-applied DB.

This is Postgres/Supabase-specific by design. The optional LOCAL_DB=sqlite dev/test
mode never runs Alembic migrations.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_per_user_rls"
down_revision = "0002_users_auth_fk"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
-- ============================================================================
-- 1. Per-user RLS on the six user-owned tables (guarded: requires Supabase auth)
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

    -- public.users : SELECT + UPDATE only -----------------------------------
    EXECUTE 'ALTER TABLE public.users ENABLE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS users_select_own ON public.users';
    EXECUTE 'CREATE POLICY users_select_own ON public.users
             FOR SELECT USING (auth.uid() = id)';
    EXECUTE 'DROP POLICY IF EXISTS users_update_own ON public.users';
    EXECUTE 'CREATE POLICY users_update_own ON public.users
             FOR UPDATE USING (auth.uid() = id) WITH CHECK (auth.uid() = id)';

    -- public.clothing_items : all four --------------------------------------
    EXECUTE 'ALTER TABLE public.clothing_items ENABLE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS clothing_items_select_own ON public.clothing_items';
    EXECUTE 'CREATE POLICY clothing_items_select_own ON public.clothing_items
             FOR SELECT USING (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS clothing_items_insert_own ON public.clothing_items';
    EXECUTE 'CREATE POLICY clothing_items_insert_own ON public.clothing_items
             FOR INSERT WITH CHECK (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS clothing_items_update_own ON public.clothing_items';
    EXECUTE 'CREATE POLICY clothing_items_update_own ON public.clothing_items
             FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS clothing_items_delete_own ON public.clothing_items';
    EXECUTE 'CREATE POLICY clothing_items_delete_own ON public.clothing_items
             FOR DELETE USING (auth.uid() = user_id)';

    -- public.item_images : all four, scoped through the parent row ----------
    EXECUTE 'ALTER TABLE public.item_images ENABLE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS item_images_select_own ON public.item_images';
    EXECUTE 'CREATE POLICY item_images_select_own ON public.item_images
             FOR SELECT USING (EXISTS (
                 SELECT 1 FROM public.clothing_items ci
                 WHERE ci.id = item_images.clothing_item_id AND ci.user_id = auth.uid()))';
    EXECUTE 'DROP POLICY IF EXISTS item_images_insert_own ON public.item_images';
    EXECUTE 'CREATE POLICY item_images_insert_own ON public.item_images
             FOR INSERT WITH CHECK (EXISTS (
                 SELECT 1 FROM public.clothing_items ci
                 WHERE ci.id = item_images.clothing_item_id AND ci.user_id = auth.uid()))';
    EXECUTE 'DROP POLICY IF EXISTS item_images_update_own ON public.item_images';
    EXECUTE 'CREATE POLICY item_images_update_own ON public.item_images
             FOR UPDATE USING (EXISTS (
                 SELECT 1 FROM public.clothing_items ci
                 WHERE ci.id = item_images.clothing_item_id AND ci.user_id = auth.uid()))
             WITH CHECK (EXISTS (
                 SELECT 1 FROM public.clothing_items ci
                 WHERE ci.id = item_images.clothing_item_id AND ci.user_id = auth.uid()))';
    EXECUTE 'DROP POLICY IF EXISTS item_images_delete_own ON public.item_images';
    EXECUTE 'CREATE POLICY item_images_delete_own ON public.item_images
             FOR DELETE USING (EXISTS (
                 SELECT 1 FROM public.clothing_items ci
                 WHERE ci.id = item_images.clothing_item_id AND ci.user_id = auth.uid()))';

    -- public.google_accounts : all four -------------------------------------
    EXECUTE 'ALTER TABLE public.google_accounts ENABLE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS google_accounts_select_own ON public.google_accounts';
    EXECUTE 'CREATE POLICY google_accounts_select_own ON public.google_accounts
             FOR SELECT USING (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS google_accounts_insert_own ON public.google_accounts';
    EXECUTE 'CREATE POLICY google_accounts_insert_own ON public.google_accounts
             FOR INSERT WITH CHECK (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS google_accounts_update_own ON public.google_accounts';
    EXECUTE 'CREATE POLICY google_accounts_update_own ON public.google_accounts
             FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS google_accounts_delete_own ON public.google_accounts';
    EXECUTE 'CREATE POLICY google_accounts_delete_own ON public.google_accounts
             FOR DELETE USING (auth.uid() = user_id)';

    -- public.user_preferences : all four (user_id is TEXT -> cast auth.uid())
    EXECUTE 'ALTER TABLE public.user_preferences ENABLE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS user_preferences_select_own ON public.user_preferences';
    EXECUTE 'CREATE POLICY user_preferences_select_own ON public.user_preferences
             FOR SELECT USING (auth.uid()::text = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS user_preferences_insert_own ON public.user_preferences';
    EXECUTE 'CREATE POLICY user_preferences_insert_own ON public.user_preferences
             FOR INSERT WITH CHECK (auth.uid()::text = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS user_preferences_update_own ON public.user_preferences';
    EXECUTE 'CREATE POLICY user_preferences_update_own ON public.user_preferences
             FOR UPDATE USING (auth.uid()::text = user_id) WITH CHECK (auth.uid()::text = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS user_preferences_delete_own ON public.user_preferences';
    EXECUTE 'CREATE POLICY user_preferences_delete_own ON public.user_preferences
             FOR DELETE USING (auth.uid()::text = user_id)';

    -- public.user_preference_events : all four (user_id is TEXT -> cast) -----
    EXECUTE 'ALTER TABLE public.user_preference_events ENABLE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS user_preference_events_select_own ON public.user_preference_events';
    EXECUTE 'CREATE POLICY user_preference_events_select_own ON public.user_preference_events
             FOR SELECT USING (auth.uid()::text = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS user_preference_events_insert_own ON public.user_preference_events';
    EXECUTE 'CREATE POLICY user_preference_events_insert_own ON public.user_preference_events
             FOR INSERT WITH CHECK (auth.uid()::text = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS user_preference_events_update_own ON public.user_preference_events';
    EXECUTE 'CREATE POLICY user_preference_events_update_own ON public.user_preference_events
             FOR UPDATE USING (auth.uid()::text = user_id) WITH CHECK (auth.uid()::text = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS user_preference_events_delete_own ON public.user_preference_events';
    EXECUTE 'CREATE POLICY user_preference_events_delete_own ON public.user_preference_events
             FOR DELETE USING (auth.uid()::text = user_id)';
END $$;

-- ============================================================================
-- 2. Lock-down RLS (enabled, no policies) on non-user tables. Idempotent.
--    Safe on alembic_version: the migration role owns the table and bypasses RLS.
-- ============================================================================
ALTER TABLE public.alembic_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.waitlist        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.weather_cache   ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- 3. Pin the trigger function's search_path (existence-guarded; see docstring).
-- ============================================================================
DO $do$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public'
          AND p.proname = 'update_user_preferences_updated_at'
    ) THEN
        EXECUTE $sql$ALTER FUNCTION public.update_user_preferences_updated_at() SET search_path = ''$sql$;
    END IF;
END
$do$;
"""


DOWNGRADE_SQL = r"""
-- Drop the per-user policies (idempotent; no-op if absent). ------------------
DROP POLICY IF EXISTS users_select_own                  ON public.users;
DROP POLICY IF EXISTS users_update_own                  ON public.users;
DROP POLICY IF EXISTS clothing_items_select_own         ON public.clothing_items;
DROP POLICY IF EXISTS clothing_items_insert_own         ON public.clothing_items;
DROP POLICY IF EXISTS clothing_items_update_own         ON public.clothing_items;
DROP POLICY IF EXISTS clothing_items_delete_own         ON public.clothing_items;
DROP POLICY IF EXISTS item_images_select_own            ON public.item_images;
DROP POLICY IF EXISTS item_images_insert_own            ON public.item_images;
DROP POLICY IF EXISTS item_images_update_own            ON public.item_images;
DROP POLICY IF EXISTS item_images_delete_own            ON public.item_images;
DROP POLICY IF EXISTS google_accounts_select_own        ON public.google_accounts;
DROP POLICY IF EXISTS google_accounts_insert_own        ON public.google_accounts;
DROP POLICY IF EXISTS google_accounts_update_own        ON public.google_accounts;
DROP POLICY IF EXISTS google_accounts_delete_own        ON public.google_accounts;
DROP POLICY IF EXISTS user_preferences_select_own       ON public.user_preferences;
DROP POLICY IF EXISTS user_preferences_insert_own       ON public.user_preferences;
DROP POLICY IF EXISTS user_preferences_update_own       ON public.user_preferences;
DROP POLICY IF EXISTS user_preferences_delete_own       ON public.user_preferences;
DROP POLICY IF EXISTS user_preference_events_select_own ON public.user_preference_events;
DROP POLICY IF EXISTS user_preference_events_insert_own ON public.user_preference_events;
DROP POLICY IF EXISTS user_preference_events_update_own ON public.user_preference_events;
DROP POLICY IF EXISTS user_preference_events_delete_own ON public.user_preference_events;

-- Disable RLS on every table this migration touched. ------------------------
ALTER TABLE public.users                  DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.clothing_items         DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.item_images            DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.google_accounts        DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_preferences       DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_preference_events DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.alembic_version        DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.waitlist               DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.weather_cache          DISABLE ROW LEVEL SECURITY;

-- Revert the function search_path hardening (existence-guarded). ------------
DO $do$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public'
          AND p.proname = 'update_user_preferences_updated_at'
    ) THEN
        EXECUTE $sql$ALTER FUNCTION public.update_user_preferences_updated_at() RESET search_path$sql$;
    END IF;
END
$do$;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
