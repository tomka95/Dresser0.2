"""Photo-seam Phase 6b: explicit, provable is_non_clothing quarantine flag

Revision ID: 0038_non_clothing_quarantine
Revises: 0037_invariant_checked_at
Create Date: 2026-07-10

The backfill sweep (Phase 6b) quarantines rows it judges non-wearable (junk
mis-filed as a closet item — a lunch bag, a hair clip) via `archived_at`, reusing
the existing hide-from-every-read-path mechanism. That worked, but left no
UNAMBIGUOUS, provable record of WHY a row is hidden: `archived_at` is also set by
a user's own "remove from closet" action, so "quarantined as non-clothing" was an
assertion, not a queryable fact.

Adds:
  * clothing_items.is_non_clothing boolean NOT NULL DEFAULT false — the explicit
    marker. A row with is_non_clothing=true is NEVER auto-hard-deleted; a human
    confirms removal separately (soft-quarantine only).
  * clothing_items.quarantine_reason text nullable — a short audit note (e.g. the
    matched keyword), never shown to the user.

Backfill: the two rows already quarantined by the live Phase 6b sweep run
(hair clip ab856300-a7b0-4c7f-938e-b8a750fa4678, lunch bag
03324695-2537-4c97-a177-394a762916ca) get is_non_clothing=true stamped so the
column is truthful for rows quarantined before this migration existed.

Additive, no CHECK, no RLS change (table is already per-user). ADD COLUMN IF NOT
EXISTS keeps re-runs safe.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0038_non_clothing_quarantine"
down_revision = "0037_invariant_checked_at"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
ALTER TABLE public.clothing_items ADD COLUMN IF NOT EXISTS is_non_clothing boolean NOT NULL DEFAULT false;
ALTER TABLE public.clothing_items ADD COLUMN IF NOT EXISTS quarantine_reason text;

UPDATE public.clothing_items
SET is_non_clothing = true, quarantine_reason = 'backfill-6b: non-wearable keyword match'
WHERE id IN (
    'ab856300-a7b0-4c7f-938e-b8a750fa4678',
    '03324695-2537-4c97-a177-394a762916ca'
) AND archived_at IS NOT NULL;
"""

DOWNGRADE_SQL = r"""
ALTER TABLE public.clothing_items DROP COLUMN IF EXISTS quarantine_reason;
ALTER TABLE public.clothing_items DROP COLUMN IF EXISTS is_non_clothing;
"""


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite (tests) gets the columns from the model metadata at create_all
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(DOWNGRADE_SQL)
