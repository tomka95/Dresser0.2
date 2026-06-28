"""image_blobs: content-addressed image dedup ledger (Wave 0 image system)

Revision ID: 0009_image_blobs
Revises: 0008_ingest_candidates_dedup
Create Date: 2026-06-28

The resolver uploaded a fresh uuid4 object to Supabase storage on every run, so
re-resolving / backfilling the same image left the old object orphaned in the
bucket. This adds a durable content-addressed dedup table: sha256(image bytes) ->
the ONE storage URL those bytes were uploaded to. The upload path (resolver
_upload -> app.utils.image_blob_store.get_or_upload) consults it before uploading,
so identical bytes are stored once across runs AND across users.

Race-safety is the PK itself: concurrent uploaders of the same bytes both PUT, but
only one row wins (INSERT ... ON CONFLICT DO NOTHING); the loser converges on the
winner's URL.

Deliberately NOT user-scoped — this is a GLOBAL dedup/cache table (no user_id). It
is the seed Wave 2a's shared image cache will EXTEND (additive columns only), not
replace.

Conventions reused from 0006/0008:
  * Raw SQL via op.execute; CREATE TABLE IF NOT EXISTS so re-applying is a no-op.
  * Inline `content_sha256 text PRIMARY KEY` => Postgres auto-names the PK
    "image_blobs_pkey", matching the ORM naming convention in app/db.py so
    `alembic check` stays green against app/models.py (ImageBlob).
  * RLS enabled (guarded on the Supabase auth schema) with NO policy: there is no
    user_id to scope by, so the table is locked to the owner/service connection the
    app uses (which bypasses RLS); anon/authenticated get no direct access.

Postgres/Supabase-specific. The optional LOCAL_DB=sqlite dev/test mode never runs
Alembic migrations.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0009_image_blobs"
down_revision = "0008_ingest_candidates_dedup"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
CREATE TABLE IF NOT EXISTS public.image_blobs (
    content_sha256 text PRIMARY KEY,
    image_url      text NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now()
);

-- Lock the table to the owner/service connection only. No per-user policy — this
-- is a GLOBAL content-addressed cache (no user_id). The owner role the app uses
-- bypasses RLS, so the ingest/backfill writers are unaffected; anon/authenticated
-- get no direct access. Guarded on the Supabase auth schema (matches 0006).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) THEN
        EXECUTE 'ALTER TABLE public.image_blobs ENABLE ROW LEVEL SECURITY';
    ELSE
        RAISE NOTICE 'auth.users absent; skipping RLS on image_blobs (non-Supabase DB).';
    END IF;
END $$;
"""


DOWNGRADE_SQL = r"""
DROP TABLE IF EXISTS public.image_blobs;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
