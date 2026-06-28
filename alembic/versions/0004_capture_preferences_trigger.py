"""capture the user_preferences updated_at function + trigger in Alembic

Revision ID: 0004_capture_preferences_trigger
Revises: 0003_per_user_rls
Create Date: 2026-06-28

Closes a from-scratch reproducibility gap. The trigger function

    public.update_user_preferences_updated_at()

and its BEFORE UPDATE trigger on public.user_preferences were created out-of-band
and lived in no migration: a DB built purely from migrations would have the
user_preferences table but neither the function nor the trigger, so updated_at
would not be maintained (and revision 0003's existence-guarded search_path ALTER
would be a no-op). This migration captures BOTH objects so a fresh build matches
live exactly.

Reproduces the live definitions verbatim (verified via pg_get_functiondef /
pg_get_triggerdef):

  * Function: plpgsql, RETURNS trigger, with search_path pinned to '' already
    baked in (so it matches the 0003 hardening with no follow-up ALTER needed).
    NOW() resolves under an empty search_path because pg_catalog is always
    implicitly present.
  * Trigger: BEFORE UPDATE FOR EACH ROW on public.user_preferences.

Idempotent: CREATE OR REPLACE FUNCTION is a no-op-replace, and the trigger is
(DROP TRIGGER IF EXISTS -> CREATE TRIGGER). Safe to re-run on the already-live DB;
correctly builds the objects on a fresh DB. No Supabase auth dependency, so it
applies on plain Postgres too (the LOCAL_DB=sqlite dev/test mode never runs
Alembic).
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0004_capture_preferences_trigger"
down_revision = "0003_per_user_rls"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
-- Function (search_path already pinned to '' to match live + revision 0003). ---
CREATE OR REPLACE FUNCTION public.update_user_preferences_updated_at()
    RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO ''
AS $function$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$function$;

-- Trigger (idempotent: drop-if-exists then create). ---------------------------
DROP TRIGGER IF EXISTS trigger_update_user_preferences_updated_at
    ON public.user_preferences;
CREATE TRIGGER trigger_update_user_preferences_updated_at
    BEFORE UPDATE ON public.user_preferences
    FOR EACH ROW
    EXECUTE FUNCTION public.update_user_preferences_updated_at();
"""


DOWNGRADE_SQL = r"""
DROP TRIGGER IF EXISTS trigger_update_user_preferences_updated_at
    ON public.user_preferences;
DROP FUNCTION IF EXISTS public.update_user_preferences_updated_at();
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
