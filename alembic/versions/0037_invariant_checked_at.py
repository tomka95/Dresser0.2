"""invariant_checked_at marker on ingest_candidates + clothing_items (P6 sweep state)

Revision ID: 0037_invariant_checked_at
Revises: 0036_manual_source_type
Create Date: 2026-07-10

Photo-seam Phase 6 (the backfill sweep): every pre-verify-v2 'ready' image must be
re-checked against the three new invariant hard gates (extra-garment / off-white /
framing). The sweep must be IDEMPOTENT and RESUMABLE without double-charging verify
calls — this nullable timestamp is the marker: NULL = never validated against
verify v2 (a sweep target), non-NULL = validated (or born v2-compliant; the card
writers stamp it at creation, since every post-P2 generated card passes the v2 gates
by construction).

Additive, no CHECK, no RLS change (both tables per-user). ADD COLUMN IF NOT EXISTS
keeps re-runs safe. Existing rows stay NULL — exactly the sweep's target set.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0037_invariant_checked_at"
down_revision = "0036_manual_source_type"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
ALTER TABLE public.ingest_candidates ADD COLUMN IF NOT EXISTS invariant_checked_at timestamptz;
ALTER TABLE public.clothing_items    ADD COLUMN IF NOT EXISTS invariant_checked_at timestamptz;
"""

DOWNGRADE_SQL = r"""
ALTER TABLE public.clothing_items    DROP COLUMN IF EXISTS invariant_checked_at;
ALTER TABLE public.ingest_candidates DROP COLUMN IF EXISTS invariant_checked_at;
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
