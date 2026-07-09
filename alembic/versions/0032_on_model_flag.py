"""on_model flag on ingest_candidates + clothing_items (G6 — no person on a closet card)

Revision ID: 0032_on_model_flag
Revises: 0031_ingest_runs_trigger_review
Create Date: 2026-07-09

Additive, backward-compatible. One boolean `on_model` (NOT NULL DEFAULT false) on both
ingest_candidates and clothing_items.

A photo cutout from an ON-MODEL source (person_count>=1 at detection) contains a person.
It is kept only as the generation/self-heal REFERENCE (image_url); the display layer never
returns it until a verified, person-free generated card lands (generation_status='ready').
This flag lets both the review deck and the closet read mask that crop. false for Gmail
items and flat-lay photos (which may still show their crop as before). No CHECK / no RLS
change (both tables are already per-user). ADD COLUMN IF NOT EXISTS keeps re-runs safe.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0032_on_model_flag"
down_revision = "0031_ingest_runs_trigger_review"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
ALTER TABLE public.ingest_candidates ADD COLUMN IF NOT EXISTS on_model boolean NOT NULL DEFAULT false;
ALTER TABLE public.clothing_items    ADD COLUMN IF NOT EXISTS on_model boolean NOT NULL DEFAULT false;
"""

DOWNGRADE_SQL = r"""
ALTER TABLE public.clothing_items    DROP COLUMN IF EXISTS on_model;
ALTER TABLE public.ingest_candidates DROP COLUMN IF EXISTS on_model;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
