"""saved_outfits like state: is_liked + liked_at (Lookbook backend)

Revision ID: 0043_saved_outfit_likes
Revises: 0042_item_cutouts
Create Date: 2026-07-11

The Lookbook (/outfits) heart used to live in a client-side array — likes were
lost on reload and analytics fired against mock outfit UUIDs. This wave gives
likes a server home so the like survives reload and every outfit_rated event
references a REAL saved_outfits row.

Schema change is minimal and additive: two columns on the EXISTING saved_outfits
table (no new table — a like is a property of a kept outfit, not a relation).

  * is_liked   boolean NOT NULL DEFAULT false — the heart state.
  * liked_at   timestamptz NULL — when the heart was last turned on; NULL while
               un-liked (kept for analytics recency, cleared on unlike).

RLS/GRANTs: saved_outfits already carries the full 4-verb per-user RLS from 0020
(auth.uid() = user_id) and the authenticated role's existing table-level
privileges cover new columns automatically — nothing to re-grant.

Conventions reused from 0021: raw SQL via op.execute; ADD COLUMN IF NOT EXISTS so
re-applying is a no-op. Additive only — the server default backfills every
existing row to un-liked.

Postgres/Supabase-specific. The optional LOCAL_DB=sqlite dev/test mode never runs
Alembic migrations (it builds the schema from app/models.py via create_all).
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0043_saved_outfit_likes"
down_revision = "0042_item_cutouts"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
ALTER TABLE public.saved_outfits
    ADD COLUMN IF NOT EXISTS is_liked boolean NOT NULL DEFAULT false;
ALTER TABLE public.saved_outfits
    ADD COLUMN IF NOT EXISTS liked_at timestamptz;
"""

DOWNGRADE_SQL = r"""
ALTER TABLE public.saved_outfits DROP COLUMN IF EXISTS liked_at;
ALTER TABLE public.saved_outfits DROP COLUMN IF EXISTS is_liked;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
