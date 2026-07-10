"""Generation observability: generation_provider + generation_cost_usd

Revision ID: 0039_generation_observability
Revises: 0038_non_clothing_quarantine
Create Date: 2026-07-10

WHY: a week of spend (~80₪) routed to the expensive on-cap generator (nano_banana)
took a full day to diagnose because NOTHING persisted which provider produced a
given image — the only evidence was two separate invoices (BFL for FLUX.2, Google
for nano) with no per-item join. These two nullable columns make nano-vs-flux volume
and spend queryable directly in Postgres:

  * generation_provider text  — the ladder rung that produced the stored card
                                 ('flux2_pro' | 'nano_banana' | 'flux_kontext' | ...).
  * generation_cost_usd numeric — that provider's per-image USD rate at generation time.

On BOTH ingest_candidates and clothing_items (the candidate value is carried to the
item at confirm). NULL until a card is generated (and NULL forever for a non-generated
gmail retailer-image item). Additive, no CHECK, no RLS change, no backfill (historical
rows predate the instrumentation and stay NULL — honestly "unknown"). ADD COLUMN IF NOT
EXISTS keeps re-runs safe.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0039_generation_observability"
down_revision = "0038_non_clothing_quarantine"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
ALTER TABLE public.ingest_candidates ADD COLUMN IF NOT EXISTS generation_provider text;
ALTER TABLE public.ingest_candidates ADD COLUMN IF NOT EXISTS generation_cost_usd numeric;
ALTER TABLE public.clothing_items    ADD COLUMN IF NOT EXISTS generation_provider text;
ALTER TABLE public.clothing_items    ADD COLUMN IF NOT EXISTS generation_cost_usd numeric;
"""

DOWNGRADE_SQL = r"""
ALTER TABLE public.ingest_candidates DROP COLUMN IF EXISTS generation_cost_usd;
ALTER TABLE public.ingest_candidates DROP COLUMN IF EXISTS generation_provider;
ALTER TABLE public.clothing_items    DROP COLUMN IF EXISTS generation_cost_usd;
ALTER TABLE public.clothing_items    DROP COLUMN IF EXISTS generation_provider;
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
