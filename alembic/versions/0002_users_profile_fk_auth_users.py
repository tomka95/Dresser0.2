"""users becomes a profile table keyed to auth.users(id)

Revision ID: 0002_users_auth_fk
Revises: 0001_baseline
Create Date: 2026-06-27

Phase 1 of the Supabase Auth cutover. Supabase Auth (auth.users) becomes the
identity source; public.users becomes a PROFILE table whose primary key is the
corresponding auth.users id. This migration adds the foreign key

    public.users.id  ->  auth.users(id)  ON DELETE CASCADE

so a profile row is keyed to (and cleaned up with) its Supabase identity.

Deliberately conservative for a live, in-transition database:

  * NO data is mutated. Only the constraint is added.
  * The constraint is added **NOT VALID**: Postgres does not scan/lock-validate
    the existing rows, so adding it to the populated live table is fast and does
    not block. (Validating historical rows is deferred to a later, coordinated
    step once legacy/orphan profiles are reconciled.)
  * It is GUARDED two ways so it is a safe no-op where it cannot apply:
      - skipped entirely if the `auth` schema / `auth.users` table is absent
        (e.g. a plain local Postgres without Supabase's auth stack), and
      - skipped if the constraint already exists (idempotent re-run).
  * Existing columns (incl. hashed_password) are intentionally KEPT — the legacy
    custom-JWT path is still live during dual-accept.

REVIEW NOTE — interaction with the legacy /signup path:
  NOT VALID skips validation of *existing* rows but Postgres still enforces the FK
  on *new* INSERTs/UPDATEs. The legacy POST /signup creates users with a random
  uuid4 id that does NOT exist in auth.users, so once this FK is live on Postgres
  those inserts will be rejected. New Supabase-provisioned profiles use the
  auth.users id (the token `sub`) and satisfy the FK. Apply this FK to the live
  database only after legacy /signup is cut over to Supabase (or retired). See the
  phase-1 report's "deferred" section.

This is Postgres-specific by design (auth.users is a Supabase/Postgres construct).
The optional LOCAL_DB=sqlite dev/test mode never runs Alembic migrations.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_users_auth_fk"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


# Constraint name follows the project naming convention (<table>_<col>_fkey),
# matching app/db.py's NAMING_CONVENTION so autogenerate stays clean.
_FK_NAME = "users_id_fkey"

UPGRADE_SQL = f"""
DO $$
BEGIN
    -- Only meaningful where Supabase's auth schema exists.
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    )
    AND NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = '{_FK_NAME}'
          AND conrelid = 'public.users'::regclass
    )
    THEN
        ALTER TABLE public.users
            ADD CONSTRAINT {_FK_NAME}
            FOREIGN KEY (id) REFERENCES auth.users (id)
            ON DELETE CASCADE
            NOT VALID;
    END IF;
END $$;
"""

DOWNGRADE_SQL = f"""
ALTER TABLE public.users DROP CONSTRAINT IF EXISTS {_FK_NAME};
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
