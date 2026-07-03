"""item_embeddings HNSW ANN index (Wave S0, Branch B)

Revision ID: 0019_item_embeddings_hnsw
Revises: 0018_stylist_data_substrate
Create Date: 2026-07-03

Branch A created item_embeddings (vector(768)) but deliberately DEFERRED the ANN index —
building an HNSW graph is cheapest once rows exist, and shipping an exotic opclass index
in the substrate migration risked an `alembic check` round-trip issue. Branch B populates
embeddings on ingest + backfill, so the index is built HERE.

HNSW (not IVFFlat): no training step, good recall without a tuned lists parameter, and it
stays correct as rows are added incrementally by the enrichment pass. vector_cosine_ops
matches how the composer will query (cosine similarity over text-embedding-004 vectors).
m=16 / ef_construction=64 are pgvector's balanced defaults.

The matching Index is also declared in app/models.py ItemEmbedding.__table_args__ (same
name), so once this migration is applied the ORM metadata and the DB agree and
`alembic check` sees no drift — exactly how the existing GIN indexes round-trip.

Postgres/pgvector-specific by design; the LOCAL_DB=sqlite dev/test path never runs
Alembic (create_all maps the vector column to a Text fallback and skips the opclass).
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0019_item_embeddings_hnsw"
down_revision = "0018_stylist_data_substrate"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
CREATE INDEX IF NOT EXISTS idx_item_embeddings_embedding_hnsw
    ON public.item_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
"""

DOWNGRADE_SQL = r"""
DROP INDEX IF EXISTS public.idx_item_embeddings_embedding_hnsw;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
