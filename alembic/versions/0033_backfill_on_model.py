"""backfill on_model for existing non-ready photo rows (G6 — mask legacy person crops)

Revision ID: 0033_backfill_on_model
Revises: 0032_on_model_flag
Create Date: 2026-07-09

0032 added on_model DEFAULT false, so EXISTING confirmed photo items (and pending photo
candidates) still show their raw crop — which, for an on-model upload, is a person. We
cannot tell per-row whether a stored crop contains a person without re-running detection,
so this backfill is CONSERVATIVE + SAFE: it flags on_model=true for every PHOTO row that
does NOT already carry a verified person-free card (generation_status IS DISTINCT FROM
'ready'). Those rows are then masked (placeholder) until the generation self-heal produces
a verified card, at which point they flip to 'ready' and un-mask automatically.

Tradeoff (stated): a legacy FLAT-LAY photo item with no ready card is masked too, until
self-heal regenerates it — the safe choice (never a person). 'ready' photo items (their
image_url IS the verified card) and all Gmail items are untouched.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0033_backfill_on_model"
down_revision = "0032_on_model_flag"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
UPDATE public.clothing_items
   SET on_model = true
 WHERE source_type = 'photo'
   AND (generation_status IS DISTINCT FROM 'ready');

UPDATE public.ingest_candidates
   SET on_model = true
 WHERE source_type = 'photo'
   AND status = 'pending'
   AND (generation_status IS DISTINCT FROM 'ready');
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    # Data backfill — not reversible (we cannot know which rows were false before). No-op.
    pass
