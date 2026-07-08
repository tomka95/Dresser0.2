"""calendar_accounts: per-user Google Calendar OAuth token store (Calendar-connect)

Revision ID: 0027_calendar_accounts
Revises: 0026_jobs_table
Create Date: 2026-07-08

Additive, backward-compatible. Ships ONE table: `calendar_accounts`, the
encrypted token store for the calendar.events.readonly connect flow (mirrors
google_accounts). NO calendar content is ever persisted — events are read live
per request; only OAuth tokens (ENCRYPTED, `v1:` ciphertext) live here.

SECURITY posture:
  * Per-user RLS (auth.uid() = user_id), 4-verb (SELECT/INSERT/UPDATE/DELETE),
    same template as google_accounts (0003).
  * ON DELETE CASCADE on user_id: deleting a user wipes their calendar tokens.
  * EXPLICIT GRANT to the `authenticated` role. This is REQUIRED, not optional:
    RLS restricts WHICH rows a role sees but does NOT itself grant table access.
    The stylist turn reads this row on an RLS-scoped connection running as
    `authenticated` (SET LOCAL role authenticated); without the grant that read
    fails and the turn 503s (see docs/stylist-chat-threat-model.md:118 — other
    tables rely on Supabase default privileges; we make it explicit here so the
    agent read provably works regardless of default-privilege coverage).

Conventions reused from 0006/0020/0026: raw SQL via op.execute; CREATE TABLE IF
NOT EXISTS with inline PK/UNIQUE/REFERENCES so Postgres auto-names them to match
the ORM naming convention (calendar_accounts_pkey, calendar_accounts_user_id_key,
calendar_accounts_user_id_fkey); RLS + GRANT guarded on the Supabase auth schema
so a non-Supabase / SQLite dev DB is a clean no-op. `alembic check` clean after
upgrade (the ORM models this table 1:1).
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0027_calendar_accounts"
down_revision = "0026_jobs_table"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
-- ============================================================================
-- calendar_accounts: per-user Google Calendar OAuth token store. Encrypted
--   tokens only (v1: ciphertext); NO calendar content is ever stored.
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.calendar_accounts (
    id            bigserial PRIMARY KEY,
    user_id       uuid NOT NULL UNIQUE REFERENCES public.users(id) ON DELETE CASCADE,
    access_token  text NOT NULL,
    refresh_token text,
    scope         text,
    token_expiry  timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
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
        RAISE NOTICE 'auth.users absent; skipping RLS/GRANT on calendar_accounts (non-Supabase DB).';
        RETURN;
    END IF;

    -- The GRANT is the critical bit: RLS alone does not grant table access, and
    -- the RLS-scoped agent turn (role authenticated) must be able to SELECT this
    -- row (and the connect flow writes it). Without this the turn 503s.
    EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON public.calendar_accounts TO authenticated';
    -- bigserial owns a sequence; the authenticated role needs USAGE to INSERT.
    EXECUTE 'GRANT USAGE, SELECT ON SEQUENCE public.calendar_accounts_id_seq TO authenticated';

    EXECUTE 'ALTER TABLE public.calendar_accounts ENABLE ROW LEVEL SECURITY';

    EXECUTE 'DROP POLICY IF EXISTS calendar_accounts_select_own ON public.calendar_accounts';
    EXECUTE 'CREATE POLICY calendar_accounts_select_own ON public.calendar_accounts
             FOR SELECT USING (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS calendar_accounts_insert_own ON public.calendar_accounts';
    EXECUTE 'CREATE POLICY calendar_accounts_insert_own ON public.calendar_accounts
             FOR INSERT WITH CHECK (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS calendar_accounts_update_own ON public.calendar_accounts';
    EXECUTE 'CREATE POLICY calendar_accounts_update_own ON public.calendar_accounts
             FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS calendar_accounts_delete_own ON public.calendar_accounts';
    EXECUTE 'CREATE POLICY calendar_accounts_delete_own ON public.calendar_accounts
             FOR DELETE USING (auth.uid() = user_id)';
END $$;
"""


DOWNGRADE_SQL = r"""
-- DROP TABLE removes the table's RLS policies; grants vanish with it.
DROP TABLE IF EXISTS public.calendar_accounts;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
