"""ingest_candidates.image_status: image lifecycle for the streaming swipe deck (Phase 4)

Revision ID: 0011_ingest_candidates_image_status
Revises: 0010_product_image_cache
Create Date: 2026-06-28

Phase 4 makes image resolution NON-BLOCKING and the swipe deck self-filling. The
extraction pass now resolves only the FAST image tiers (inline / email-img / cache)
inline, so the deck appears immediately; the SLOW tiers (og:image / feed / search)
run in a background fill task that streams images onto cards as they resolve. The
frontend needs to know, per candidate, whether an image is present, still resolving,
or exhausted — so it can sort image-present cards first, show a shimmer placeholder
while resolution is in flight, and stop polling once nothing is pending.

One additive column on ingest_candidates:

  * image_status (resolved | placeholder | pending | user_uploaded) : the per-candidate
    image lifecycle, mirroring clothing_items.image_status (migration 0010) EXACTLY —
    same enum vocabulary, same named-CHECK pattern, NULL allowed. The background fill
    sets 'resolved' when a verified image lands and 'placeholder' once the slow tiers
    are exhausted with nothing found; extraction stages 'resolved'/'pending'.

Backfill existing rows from current image presence (image_url non-null -> 'resolved',
else 'pending'), matching the 0010 clothing_items backfill so old candidates carry a
consistent status.

Conventions reused from 0006/0008/0010: raw SQL via op.execute; ADD COLUMN IF NOT
EXISTS + guarded ADD CONSTRAINT so re-applying is a no-op; the CHECK is auto-named
ingest_candidates_image_status_check to match the ORM naming convention in app/db.py,
keeping `alembic check` green against app/models.py (the new IngestCandidate column +
CheckConstraint(name='image_status')).

Postgres/Supabase-specific. The optional LOCAL_DB=sqlite dev/test mode never runs
Alembic migrations.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0011_ingest_candidates_image_status"
down_revision = "0010_product_image_cache"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
ALTER TABLE public.ingest_candidates
    ADD COLUMN IF NOT EXISTS image_status text;

-- image_status enum guard (named CHECK; not diffed by autogenerate). NULL allowed.
-- Same vocabulary as clothing_items_image_status_check (migration 0010).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'public'
          AND table_name = 'ingest_candidates'
          AND constraint_name = 'ingest_candidates_image_status_check'
    ) THEN
        ALTER TABLE public.ingest_candidates
            ADD CONSTRAINT ingest_candidates_image_status_check
            CHECK (image_status IS NULL OR image_status IN
                   ('resolved','placeholder','pending','user_uploaded'));
    END IF;
END $$;

-- Backfill: status from current image presence (mirrors the 0010 clothing_items pass).
UPDATE public.ingest_candidates
   SET image_status = CASE
       WHEN image_url IS NOT NULL AND image_url <> '' THEN 'resolved'
       ELSE 'pending'
   END
 WHERE image_status IS NULL;
"""


DOWNGRADE_SQL = r"""
ALTER TABLE public.ingest_candidates
    DROP CONSTRAINT IF EXISTS ingest_candidates_image_status_check;

ALTER TABLE public.ingest_candidates
    DROP COLUMN IF EXISTS image_status;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
