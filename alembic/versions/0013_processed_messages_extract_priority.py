"""processed_messages.extract_priority: clothing-likely-first extraction queue

Revision ID: 0013_processed_messages_extract_priority
Revises: 0012_ingest_runs_cost
Create Date: 2026-06-28

Feature A (progressive deck): to surface the first swipeable card within seconds, the
extraction phase orders its LLM queue CLOTHING-LIKELY FIRST. The rank is computed
cheaply at FETCH time (sender is a known clothing/retail brand, or the subject mentions
a garment term — receipt_filter.clothing_priority), where the headers are already in
hand, and persisted here so the extraction pass can simply ORDER BY it.

  * extract_priority smallint : 0 = clothing-likely (extract first), 1 = other.
    NOT NULL DEFAULT 1 so pre-existing rows sort after newly-classified clothing-likely
    ones (and the app never null-checks).

This only ORDERS the queue; every kept email is still extracted and the LLM clothing
gate stays authoritative.

Conventions reused from 0006-0012: raw SQL via op.execute; ADD COLUMN IF NOT EXISTS so
re-applying is a no-op. Column type (smallint) mirrors the ORM (ProcessedMessage,
SmallInteger) so `alembic check` stays green; the server default lives here
(compare_server_default is off in env.py).

Postgres/Supabase-specific. The optional LOCAL_DB=sqlite dev/test mode never runs
Alembic migrations.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0013_processed_messages_extract_priority"
down_revision = "0012_ingest_runs_cost"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
ALTER TABLE public.processed_messages
    ADD COLUMN IF NOT EXISTS extract_priority smallint NOT NULL DEFAULT 1;
"""


DOWNGRADE_SQL = r"""
ALTER TABLE public.processed_messages
    DROP COLUMN IF EXISTS extract_priority;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
