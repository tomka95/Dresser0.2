"""clothing_items.generation_status: carry the generated-card lifecycle to the closet (Wave 2)

Revision ID: 0017_clothing_items_generation_status
Revises: 0016_ingest_candidate_generation
Create Date: 2026-07-02

Wave 2 confirm-attach: when a photo candidate with generation_status='ready' is
confirmed, clothing_items.image_url is set to the VERIFIED generated product card
(candidate.generated_image_url), not the raw crop. Every other case — pending_retry /
failed / null (no verified card) — falls back to the crop so the item still has an
image. This column carries the candidate's generation_status onto the closet row so:

  * 'ready'        : image_url IS the generated card;
  * 'pending_retry': image_url is the crop fallback — a later generation self-heal
                     sweep queries these rows and re-attempts (image_url is the crop it
                     regenerates from);
  * 'failed'       : crop, terminal;
  * NULL           : not a generation item (Gmail / manual) — unchanged behavior.

One additive column on clothing_items:

  * generation_status (generating | ready | failed | pending_retry) : mirrors
    ingest_candidates.generation_status (migration 0016) EXACTLY — same enum, same
    named-CHECK pattern, NULL allowed.

Conventions reused from 0011/0016: raw SQL via op.execute; ADD COLUMN IF NOT EXISTS +
guarded ADD CONSTRAINT so re-applying is a no-op; the CHECK is auto-named
clothing_items_generation_status_check to match the ORM naming convention in app/db.py,
keeping `alembic check` green against app/models.py (the new column + CheckConstraint
name='generation_status'). Additive only — no backfill (existing rows stay NULL).

Postgres/Supabase-specific. The optional LOCAL_DB=sqlite dev/test mode never runs
Alembic migrations (it builds the schema from app/models.py via create_all).
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0017_clothing_items_generation_status"
down_revision = "0016_ingest_candidate_generation"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
ALTER TABLE public.clothing_items
    ADD COLUMN IF NOT EXISTS generation_status text;

-- generation_status enum guard (named CHECK; not diffed by autogenerate). NULL allowed.
-- Same vocabulary as ingest_candidates_generation_status_check (migration 0016).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'public'
          AND table_name = 'clothing_items'
          AND constraint_name = 'clothing_items_generation_status_check'
    ) THEN
        ALTER TABLE public.clothing_items
            ADD CONSTRAINT clothing_items_generation_status_check
            CHECK (generation_status IS NULL OR generation_status IN
                   ('generating','ready','failed','pending_retry'));
    END IF;
END $$;
"""


DOWNGRADE_SQL = r"""
ALTER TABLE public.clothing_items
    DROP CONSTRAINT IF EXISTS clothing_items_generation_status_check;
ALTER TABLE public.clothing_items
    DROP COLUMN IF EXISTS generation_status;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
