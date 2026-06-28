"""ingest_runs: add total_estimate column (phase 3b)

Revision ID: 0007_ingest_runs_total_estimate
Revises: 0006_ingestion_schema
Create Date: 2026-06-28

Adds nullable integer column total_estimate to ingest_runs so the background
worker can store the Gmail resultSizeEstimate captured at list-phase time.
The status endpoint surfaces this as progress.total_estimate for a "X of Y"
UX. NULL until the list phase completes (safe default).
"""
from alembic import op

revision = "0007_ingest_runs_total_estimate"
down_revision = "0006_ingestion_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.ingest_runs
            ADD COLUMN IF NOT EXISTS total_estimate integer;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.ingest_runs
            DROP COLUMN IF EXISTS total_estimate;
        """
    )
