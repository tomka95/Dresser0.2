"""saved_outfits feedback lifecycle: status + worn_at + feedback (Wave S3)

Revision ID: 0021_saved_outfit_feedback
Revises: 0020_stylist_chat
Create Date: 2026-07-04

Wave S3 closes the outfit learning loop. Today only ``outfit_accept`` fires (a kept
outfit -> a saved_outfits row); reject / modify / worn were reserved in the S0 event
taxonomy but never wired. This wave adds the feedback endpoint + attribute-level
credit assignment (per-item preference_signals with source='outfit_feedback', which
the s3a distill/redistill pipeline already weights ABOVE inferred and BELOW explicit).

Schema change is minimal and additive: three columns on the EXISTING saved_outfits
table so a saved outfit can carry the feedback the user later gives it. Composed-but-
unsaved outfits (rejected/modified in chat before ever being kept) need no row — the
feedback endpoint fans them straight into style_events + preference_signals from their
item ids. These columns are only for outfits that WERE saved and then reacted to.

  * status      text NOT NULL DEFAULT 'active'
                ('active' | 'worn' | 'rejected' | 'archived'). Named CHECK, mirrors
                the ORM CheckConstraint(name='status') -> saved_outfits_status_check.
  * worn_at     timestamptz NULL — set when the user taps "wore it" (outfit_worn).
  * feedback    jsonb NULL — PII-free carrier for the last feedback applied
                ({feedback, reason_chips, slot, direction, signals}); NULL until first.

Conventions reused from 0011/0016/0017: raw SQL via op.execute; ADD COLUMN IF NOT
EXISTS + guarded ADD CONSTRAINT so re-applying is a no-op; the CHECK is auto-named
saved_outfits_status_check to match the ORM naming convention (app/db.py), keeping
`alembic check` green against app/models.py. Additive only — the server default
backfills every existing row to 'active' (no separate UPDATE needed).

Postgres/Supabase-specific. The optional LOCAL_DB=sqlite dev/test mode never runs
Alembic migrations (it builds the schema from app/models.py via create_all).
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0021_saved_outfit_feedback"
down_revision = "0020_stylist_chat"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
ALTER TABLE public.saved_outfits
    ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'active';
ALTER TABLE public.saved_outfits
    ADD COLUMN IF NOT EXISTS worn_at timestamptz;
ALTER TABLE public.saved_outfits
    ADD COLUMN IF NOT EXISTS feedback jsonb;

-- status enum guard (named CHECK; not diffed by autogenerate). NOT NULL + default
-- 'active' above means every legacy row is already valid.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'public'
          AND table_name = 'saved_outfits'
          AND constraint_name = 'saved_outfits_status_check'
    ) THEN
        ALTER TABLE public.saved_outfits
            ADD CONSTRAINT saved_outfits_status_check
            CHECK (status IN ('active','worn','rejected','archived'));
    END IF;
END $$;
"""


DOWNGRADE_SQL = r"""
ALTER TABLE public.saved_outfits
    DROP CONSTRAINT IF EXISTS saved_outfits_status_check;
ALTER TABLE public.saved_outfits
    DROP COLUMN IF EXISTS feedback;
ALTER TABLE public.saved_outfits
    DROP COLUMN IF EXISTS worn_at;
ALTER TABLE public.saved_outfits
    DROP COLUMN IF EXISTS status;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
