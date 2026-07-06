"""products corpus + product_embeddings (Wave F1b: shopping-feed catalog)

Revision ID: 0022_products_corpus
Revises: 0021_saved_outfit_feedback
Create Date: 2026-07-06

The shopping-feed's proprietary catalog. Two SHARED, cross-user tables — the
byproduct of resolving product pages once and serving them to everyone — mirroring
product_image_cache (0010) and image_blobs (0009):

  1. products : one row per discovered garment product page, extracted into our
     UNIVERSAL garment schema (the same category/subcategory/color/pattern/material/
     fit/formality/warmth/seasons/occasions vocabulary as clothing_items) plus
     merchant / brand / name / urls / price / currency / geo_markets / stock. source
     is search|feed|manual. attributes_json carries per-field confidence+provenance
     (same shape as clothing_items.attributes_json). first_seen/last_seen/last_checked
     + active track corpus freshness.

     BOUNDARY (structural, from day one): products holds garment attributes + price
     ONLY. There is deliberately NO affiliate id, payout, or click/redirect URL here
     — monetization is a separate module (F1c) so ranking code can never read a payout
     field. Keep it that way.

  2. product_embeddings : pgvector side table, FK -> products, vector(768) in the
     SAME space as item_embeddings (gemini-embedding-001, EMBEDDING_DIM/VERSION pinned
     identical) so taste_match = cosine(product, closet-centroid) works directly.
     UNIQUE(product_id, model, version) for re-embedding in place; HNSW cosine index
     copied verbatim from 0019 (m=16, ef_construction=64). Empty at create time, so the
     index builds instantly and stays correct as the ingest harness adds rows.

  SHARED catalog reference data: NEITHER table has user_id / message / order data.
  RLS enabled with NO policy on both (owner/service writes; anon/authenticated denied),
  mirroring product_image_cache (0010) and image_blobs (0009). Guarded on Supabase auth.

Conventions reused from 0009/0010/0018/0019: raw SQL via op.execute; CREATE TABLE /
INDEX IF NOT EXISTS; inline PRIMARY KEY / UNIQUE / REFERENCES so Postgres auto-names
them to match the ORM naming convention in app/db.py (products_pkey,
products_canonical_url_key, product_embeddings_product_id_model_version_key,
product_embeddings_product_id_fkey), keeping `alembic check` green against
app/models.py (Product + ProductEmbedding). Named CHECKs are not diffed by autogenerate.

Postgres/pgvector/Supabase-specific. The optional LOCAL_DB=sqlite dev/test mode never
runs Alembic (create_all maps vector -> Text and text[] -> JSON, and skips RLS/opclass).
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0022_products_corpus"
down_revision = "0021_saved_outfit_feedback"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
-- pgvector already enabled by 0018; harmless if re-run.
CREATE EXTENSION IF NOT EXISTS "vector";

-- ============================================================================
-- (1) products: shared, cross-user garment catalog (attributes + price ONLY)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.products (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source            text NOT NULL,
    merchant          text,
    brand             text,
    name              text NOT NULL,
    canonical_url     text UNIQUE,
    product_url       text NOT NULL,
    image_url         text,                 -- OURS, verified; NULL until a verify pass
    price             numeric,
    currency          text,
    category          text,
    subcategory       text,                 -- free text; external products need not map to the 72 enum
    color_primary     text,
    color_primary_hex text,
    color_secondary   text,
    pattern           text,
    material          text,
    fit_silhouette    text,
    formality         integer,
    warmth            integer,
    seasons           text[],
    occasions         text[],
    geo_markets       text[],
    in_stock          boolean,
    attributes_json   jsonb NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at     timestamptz NOT NULL DEFAULT now(),
    last_seen_at      timestamptz NOT NULL DEFAULT now(),
    last_checked_at   timestamptz,
    active            boolean NOT NULL DEFAULT true,
    CONSTRAINT products_source_check
        CHECK (source IN ('search','feed','manual')),
    CONSTRAINT products_category_check
        CHECK (category IS NULL OR category IN (
            'top','bottom','dress','outerwear','footwear','bag','accessory',
            'activewear','swim','lounge_underwear','suiting','jewelry',
            'shoes','accessories','other')),
    CONSTRAINT products_formality_check
        CHECK (formality IS NULL OR (formality >= 1 AND formality <= 5)),
    CONSTRAINT products_warmth_check
        CHECK (warmth IS NULL OR (warmth >= 1 AND warmth <= 3)),
    CONSTRAINT products_currency_len_check
        CHECK (currency IS NULL OR length(currency) = 3)
);

-- Cheap lookups the ranker/backfill lean on (freshness sweep + category slices).
CREATE INDEX IF NOT EXISTS idx_products_active_last_seen
    ON public.products USING btree (active, last_seen_at);
CREATE INDEX IF NOT EXISTS idx_products_category
    ON public.products USING btree (category);

-- ============================================================================
-- (2) product_embeddings: pgvector side table in the item_embeddings space
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.product_embeddings (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id uuid NOT NULL REFERENCES public.products(id) ON DELETE CASCADE,
    embedding  vector(768) NOT NULL,
    model      text NOT NULL,
    dim        integer NOT NULL,
    version    integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT product_embeddings_product_id_model_version_key
        UNIQUE (product_id, model, version)
);

-- HNSW cosine index — copied verbatim from 0019 (item_embeddings). Same space, same
-- opclass and params so product<->closet cosine is directly comparable.
CREATE INDEX IF NOT EXISTS idx_product_embeddings_embedding_hnsw
    ON public.product_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ============================================================================
-- (3) RLS, no policy: shared catalog. Owner/service writes; anon/authenticated
--     denied. Guarded on Supabase auth (mirrors product_image_cache / image_blobs).
-- ============================================================================
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) THEN
        EXECUTE 'ALTER TABLE public.products ENABLE ROW LEVEL SECURITY';
        EXECUTE 'ALTER TABLE public.product_embeddings ENABLE ROW LEVEL SECURITY';
    ELSE
        RAISE NOTICE 'auth.users absent; skipping RLS on products/product_embeddings (non-Supabase DB).';
    END IF;
END $$;
"""


DOWNGRADE_SQL = r"""
DROP INDEX IF EXISTS public.idx_product_embeddings_embedding_hnsw;
DROP TABLE IF EXISTS public.product_embeddings;
DROP INDEX IF EXISTS public.idx_products_category;
DROP INDEX IF EXISTS public.idx_products_active_last_seen;
DROP TABLE IF EXISTS public.products;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
