"""Photo-seam Phase 4: 'manual' joins the source_type CHECKs (the confirm chokepoint)

Revision ID: 0036_manual_source_type
Revises: 0035_pipeline_state_person_status
Create Date: 2026-07-09

Phase 4 makes the confirm path THE single way a clothing_item is born: every entry
point stages an ingest_candidate and only a 'ready' candidate (verified, person-free,
invariant-compliant card + complete tags) may be confirmed into the closet. A typed
MANUAL add therefore becomes a candidate too — source_type='manual' — with its own
1-candidate ingest_run so the shared settle/status/strand-heal machinery covers it.

This migration widens the three named source_type CHECKs to admit 'manual':
  * ingest_candidates.source_type  IN ('gmail','photo','manual')
  * ingest_runs.source_type        IN ('gmail','photo','manual')
  * clothing_items.source_type     IN ('gmail','photo','manual')

Named CHECKs are not diffed by autogenerate; DROP IF EXISTS + ADD keeps re-runs safe.
No data change, no RLS change, no PII.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0036_manual_source_type"
down_revision = "0035_pipeline_state_person_status"
branch_labels = None
depends_on = None


# The live DB's constraints carry the conventional names (<table>_source_type_check,
# MCP-verified 2026-07-09); the model metadata names them 'source_type' (what SQLite
# test DBs get from create_all). Drop BOTH spellings, recreate under the live name.
UPGRADE_SQL = r"""
ALTER TABLE public.ingest_candidates
    DROP CONSTRAINT IF EXISTS source_type;
ALTER TABLE public.ingest_candidates
    DROP CONSTRAINT IF EXISTS ingest_candidates_source_type_check;
ALTER TABLE public.ingest_candidates
    ADD CONSTRAINT ingest_candidates_source_type_check
    CHECK (source_type IN ('gmail','photo','manual'));

ALTER TABLE public.ingest_runs
    DROP CONSTRAINT IF EXISTS source_type;
ALTER TABLE public.ingest_runs
    DROP CONSTRAINT IF EXISTS ingest_runs_source_type_check;
ALTER TABLE public.ingest_runs
    ADD CONSTRAINT ingest_runs_source_type_check
    CHECK (source_type IN ('gmail','photo','manual'));

ALTER TABLE public.clothing_items
    DROP CONSTRAINT IF EXISTS source_type;
ALTER TABLE public.clothing_items
    DROP CONSTRAINT IF EXISTS clothing_items_source_type_check;
ALTER TABLE public.clothing_items
    ADD CONSTRAINT clothing_items_source_type_check
    CHECK (source_type IN ('gmail','photo','manual'));
"""

DOWNGRADE_SQL = r"""
ALTER TABLE public.ingest_candidates
    DROP CONSTRAINT IF EXISTS ingest_candidates_source_type_check;
ALTER TABLE public.ingest_candidates
    ADD CONSTRAINT ingest_candidates_source_type_check
    CHECK (source_type IN ('gmail','photo'));

ALTER TABLE public.ingest_runs
    DROP CONSTRAINT IF EXISTS ingest_runs_source_type_check;
ALTER TABLE public.ingest_runs
    ADD CONSTRAINT ingest_runs_source_type_check
    CHECK (source_type IN ('gmail','photo'));

ALTER TABLE public.clothing_items
    DROP CONSTRAINT IF EXISTS clothing_items_source_type_check;
ALTER TABLE public.clothing_items
    ADD CONSTRAINT clothing_items_source_type_check
    CHECK (source_type IN ('gmail','photo'));
"""


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite (tests) gets the widened CHECK from the model metadata at create_all.
        return
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(DOWNGRADE_SQL)
