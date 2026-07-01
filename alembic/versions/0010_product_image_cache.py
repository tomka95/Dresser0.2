"""product_image_cache + merchant/image-status on clothing_items (Wave 2a)

Revision ID: 0010_product_image_cache
Revises: 0009_image_blobs
Create Date: 2026-06-28

Wave 2a of the image system. Four pieces:

  1. product_image_cache : the shared, cross-user resolve-once-serve-many cache
     (the proprietary-catalog byproduct). Keyed by cache_key = hash of normalized
     brand+name+color (app/gmail_closet/product_image_cache.py). image_url points
     at an image_blobs blob (content_sha256 FK). verified defaults FALSE; ONLY
     verified rows are ever served, and ONLY the later vision-verify wave flips
     verified true — so the resolver's cache read tier is a safe no-op until then.
     Shared catalog reference data: NO user_id / message / order data. RLS enabled
     with no policy (owner/service writes; anon/authenticated denied), mirroring
     image_blobs (0009).

  2. clothing_items.merchant : merchant is now PERSISTED at confirm (review_service)
     instead of joined from ingest_candidates at display time (closet.py).

  3. clothing_items.image_status (resolved|placeholder|pending|user_uploaded) +
     image_cache_key : image lifecycle fields for self-healing (additive, no
     behavior change yet). image_status guarded by a named CHECK (NULL allowed).

  4. Data backfill: merchant from each row's contributing ingest_candidate (matched
     on user_id + source_line_key), and image_status from current image_url presence.

Conventions reused from 0006/0008/0009: raw SQL via op.execute; CREATE TABLE /
ADD COLUMN IF NOT EXISTS + guarded ADD CONSTRAINT so re-applying is a no-op; inline
PRIMARY KEY / UNIQUE / REFERENCES so Postgres auto-names them to match the ORM
naming convention in app/db.py (product_image_cache_pkey /
product_image_cache_cache_key_key / product_image_cache_content_sha256_fkey /
clothing_items_image_status_check), keeping `alembic check` green against
app/models.py (ProductImageCache + the new ClothingItem columns).

Postgres/Supabase-specific. The optional LOCAL_DB=sqlite dev/test mode never runs
Alembic migrations.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0010_product_image_cache"
down_revision = "0009_image_blobs"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
-- ============================================================================
-- (1) product_image_cache: shared, cross-user, verified-only-serve image cache
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.product_image_cache (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cache_key      text NOT NULL UNIQUE,
    brand          text,
    name_norm      text,
    color_norm     text,
    image_url      text NOT NULL,
    content_sha256 text REFERENCES public.image_blobs(content_sha256) ON DELETE SET NULL,
    source_tier    text,
    source_domain  text,
    verified       boolean NOT NULL DEFAULT false,
    verify_score   numeric,
    created_at     timestamptz NOT NULL DEFAULT now(),
    last_served_at timestamptz,
    serve_count    integer NOT NULL DEFAULT 0
);

-- RLS, no policy: locked to the owner/service connection the app uses (which
-- bypasses RLS); anon/authenticated get no direct access. Guarded on Supabase auth.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) THEN
        EXECUTE 'ALTER TABLE public.product_image_cache ENABLE ROW LEVEL SECURITY';
    ELSE
        RAISE NOTICE 'auth.users absent; skipping RLS on product_image_cache (non-Supabase DB).';
    END IF;
END $$;

-- ============================================================================
-- (2)+(3) clothing_items: merchant + image lifecycle fields
-- ============================================================================
ALTER TABLE public.clothing_items
    ADD COLUMN IF NOT EXISTS merchant        text,
    ADD COLUMN IF NOT EXISTS image_status    text,
    ADD COLUMN IF NOT EXISTS image_cache_key text;

-- image_status enum guard (named CHECK; not diffed by autogenerate). NULL allowed.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'public'
          AND table_name = 'clothing_items'
          AND constraint_name = 'clothing_items_image_status_check'
    ) THEN
        ALTER TABLE public.clothing_items
            ADD CONSTRAINT clothing_items_image_status_check
            CHECK (image_status IS NULL OR image_status IN
                   ('resolved','placeholder','pending','user_uploaded'));
    END IF;
END $$;

-- ============================================================================
-- (4) Backfill existing rows
-- ============================================================================
-- merchant from the contributing candidate (UNIQUE(user_id, source_line_key) means
-- one candidate per key; DISTINCT ON is belt-and-suspenders / newest wins).
UPDATE public.clothing_items ci
   SET merchant = sub.merchant
  FROM (
      SELECT DISTINCT ON (user_id, source_line_key)
             user_id, source_line_key, merchant
        FROM public.ingest_candidates
       WHERE source_line_key IS NOT NULL AND merchant IS NOT NULL
       ORDER BY user_id, source_line_key, created_at DESC
  ) sub
 WHERE ci.merchant IS NULL
   AND ci.source_line_key IS NOT NULL
   AND ci.user_id = sub.user_id
   AND ci.source_line_key = sub.source_line_key;

-- image_status from current image presence (image_cache_key left NULL for legacy
-- rows — it needs the app-side normalization and is set going forward at confirm).
UPDATE public.clothing_items
   SET image_status = CASE
       WHEN image_url IS NOT NULL AND image_url <> '' THEN 'resolved'
       ELSE 'pending'
   END
 WHERE image_status IS NULL;
"""


DOWNGRADE_SQL = r"""
ALTER TABLE public.clothing_items
    DROP CONSTRAINT IF EXISTS clothing_items_image_status_check;

ALTER TABLE public.clothing_items
    DROP COLUMN IF EXISTS merchant,
    DROP COLUMN IF EXISTS image_status,
    DROP COLUMN IF EXISTS image_cache_key;

DROP TABLE IF EXISTS public.product_image_cache;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
