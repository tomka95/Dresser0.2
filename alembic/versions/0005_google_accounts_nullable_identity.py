"""relax google_accounts.google_sub/email to nullable for the Gmail-connect flow

Revision ID: 0005_google_accounts_nullable_identity
Revises: 0004_capture_preferences_trigger
Create Date: 2026-06-28

The dedicated "Tailor Gmail Ingest" OAuth client requests gmail.readonly ONLY --
no identity scopes -- so the connect flow that writes google_accounts has no
Google subject id (google_sub) or email to record. Identity is owned entirely by
Supabase Auth; google_accounts is now purely the per-user encrypted Gmail token
store, keyed by user_id (UNIQUE).

Baseline 0001 created both columns NOT NULL. This relaxes them so a row can be
written with only the token material. No data change; widening NULLability is
safe on existing rows.

Downgrade re-imposes NOT NULL. Because rows written by the connect flow may have
NULL google_sub/email, the downgrade first backfills NULLs with '' so the ALTER
cannot fail. (Lossy but reversible-in-shape; the '' sentinel is indistinguishable
from "unknown", which is acceptable for a rollback path.)
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0005_google_accounts_nullable_identity"
down_revision = "0004_capture_preferences_trigger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.google_accounts ALTER COLUMN google_sub DROP NOT NULL;")
    op.execute("ALTER TABLE public.google_accounts ALTER COLUMN email DROP NOT NULL;")


def downgrade() -> None:
    op.execute("UPDATE public.google_accounts SET google_sub = '' WHERE google_sub IS NULL;")
    op.execute("UPDATE public.google_accounts SET email = '' WHERE email IS NULL;")
    op.execute("ALTER TABLE public.google_accounts ALTER COLUMN google_sub SET NOT NULL;")
    op.execute("ALTER TABLE public.google_accounts ALTER COLUMN email SET NOT NULL;")
