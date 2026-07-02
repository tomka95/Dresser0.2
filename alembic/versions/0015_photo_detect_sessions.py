"""photo detect sessions: transient detect -> select -> commit handoff (Wave 1.5)

Revision ID: 0015_photo_detect_sessions
Revises: 0014_photo_ingest
Create Date: 2026-07-02

Wave 1.5 splits the atomic photo pipeline (detect + cutout + stage in one request)
into detect-only -> user region selection -> commit-selected. Between the two steps
the detected regions must live SOMEWHERE — and it must not be the source photo
(which is never persisted to storage, before or after this change). This table is
that somewhere: a short-lived, per-user session row holding the detection output
(boxes + optional masks + attributes as JSONB) keyed by the photo's sha256, so the
commit request can re-receive the same file and bind it back to its detection.

Rows are transient by design: expires_at (config PHOTO_SESSION_TTL_HOURS) bounds
their life, detect sweeps a user's expired 'pending' rows opportunistically, and a
successful commit flips status to 'committed'. No image bytes are ever stored here —
only hashes, dimensions, boxes, and (model-produced) mask PNGs scoped to a box.

Per-user RLS (auth.uid() = user_id), exactly matching 0014's processed_uploads.

Conventions reused from 0006/0008/0014: raw SQL via op.execute; CREATE TABLE IF NOT
EXISTS + guarded RLS DO block so re-applying is a no-op; constraint/index names match
the ORM naming convention in app/db.py so `alembic check` stays green against
app/models.py.

Postgres/Supabase-specific (uuid, gen_random_uuid(), jsonb, RLS) by design. The
optional LOCAL_DB=sqlite dev/test mode never runs Alembic migrations.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0015_photo_detect_sessions"
down_revision = "0014_photo_ingest"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
-- ============================================================================
-- photo_detect_sessions: transient detection results awaiting user selection.
-- regions = [{region_id, box_2d[4], mask|null, name, category, color, pattern,
--             material, fit, brand, confidence_overall, confidence{...}}]
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.photo_detect_sessions (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    image_sha256  text NOT NULL,
    phash         text,
    width         integer NOT NULL,
    height        integer NOT NULL,
    person_count  integer NOT NULL DEFAULT 0,
    regions       jsonb NOT NULL DEFAULT '[]'::jsonb,
    status        text NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending','committed','expired')),
    created_at    timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_photo_detect_sessions_user_id
    ON public.photo_detect_sessions USING btree (user_id);
CREATE INDEX IF NOT EXISTS idx_photo_detect_sessions_user_sha
    ON public.photo_detect_sessions USING btree (user_id, image_sha256);

-- Per-user RLS (guarded: requires the Supabase auth schema). user_id is UUID ->
-- compare auth.uid() directly, no ::text cast (matches the 0014 table).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) THEN
        RAISE NOTICE 'auth.users absent; skipping per-user RLS (non-Supabase DB).';
        RETURN;
    END IF;

    EXECUTE 'ALTER TABLE public.photo_detect_sessions ENABLE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS photo_detect_sessions_select_own ON public.photo_detect_sessions';
    EXECUTE 'CREATE POLICY photo_detect_sessions_select_own ON public.photo_detect_sessions
             FOR SELECT USING (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS photo_detect_sessions_insert_own ON public.photo_detect_sessions';
    EXECUTE 'CREATE POLICY photo_detect_sessions_insert_own ON public.photo_detect_sessions
             FOR INSERT WITH CHECK (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS photo_detect_sessions_update_own ON public.photo_detect_sessions';
    EXECUTE 'CREATE POLICY photo_detect_sessions_update_own ON public.photo_detect_sessions
             FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS photo_detect_sessions_delete_own ON public.photo_detect_sessions';
    EXECUTE 'CREATE POLICY photo_detect_sessions_delete_own ON public.photo_detect_sessions
             FOR DELETE USING (auth.uid() = user_id)';
END $$;
"""


DOWNGRADE_SQL = r"""
DROP TABLE IF EXISTS public.photo_detect_sessions;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
