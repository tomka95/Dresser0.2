"""monetization: product_clicks + affiliate_conversions (Wave F1c)

Revision ID: 0023_monetization
Revises: 0022_products_corpus
Create Date: 2026-07-06

The click-time redirect substrate, isolated from ranking on purpose (see app/monetization).

  1. product_clicks : one row per outbound product click. id IS the opaque click_id
     (uuid) the frontend links to at /out/{click_id}. Records who clicked (user_id),
     what (product_id), from where (surface feed|search|chat|deck + card_type), and how
     it was resolved (wrapped bool, network). PER-USER RLS (auth.uid() = user_id), the
     0018 pattern — a user's click history is their own.

  2. affiliate_conversions : network postbacks (order_value / commission / status),
     joined to a click only by click_id. SERVICE-ONLY: RLS enabled with NO policy
     (owner/service writes; anon/authenticated denied), mirroring product_image_cache.
     It carries NO user_id and is deliberately structurally invisible to ranking and to
     any user-facing query — payout data must never be reachable from the feed ranker.

Conventions reused from 0010/0018/0022: raw SQL via op.execute; CREATE TABLE IF NOT
EXISTS; inline PK/UNIQUE/REFERENCES so Postgres auto-names them to match the ORM naming
convention (product_clicks_pkey, product_clicks_user_id_fkey, ...); named CHECKs (not
diffed by autogenerate); RLS guarded on the Supabase auth schema.

Postgres/Supabase-specific. LOCAL_DB=sqlite dev/test never runs Alembic (create_all;
RLS skipped).
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0023_monetization"
down_revision = "0022_products_corpus"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
-- ============================================================================
-- (1) product_clicks: opaque click_id -> outbound click record. PER-USER RLS.
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.product_clicks (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),   -- IS the click_id
    user_id     uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    product_id  uuid REFERENCES public.products(id) ON DELETE SET NULL,
    surface     text NOT NULL,
    card_type   text,
    wrapped     boolean NOT NULL DEFAULT false,
    network     text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT product_clicks_surface_check
        CHECK (surface IN ('feed','search','chat','deck'))
);
CREATE INDEX IF NOT EXISTS idx_product_clicks_user_created
    ON public.product_clicks USING btree (user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_product_clicks_product
    ON public.product_clicks USING btree (product_id);

-- ============================================================================
-- (2) affiliate_conversions: network postbacks. SERVICE-ONLY (RLS, no policy).
--     NO user_id; attribution is via click_id join, done only in service code.
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.affiliate_conversions (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    click_id    uuid REFERENCES public.product_clicks(id) ON DELETE SET NULL,
    network     text,
    order_value numeric,
    commission  numeric,
    status      text,
    reported_at timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_affiliate_conversions_click
    ON public.affiliate_conversions USING btree (click_id);

-- ============================================================================
-- (3) RLS. Guarded on Supabase auth.
--     product_clicks : per-user (4 policies, auth.uid() = user_id).
--     affiliate_conversions : ENABLE, NO policy (service-only).
-- ============================================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) THEN
        RAISE NOTICE 'auth.users absent; skipping RLS on monetization tables (non-Supabase DB).';
        RETURN;
    END IF;

    -- product_clicks: per-user policies (0018 pattern, UUID user_id, no ::text cast).
    EXECUTE 'ALTER TABLE public.product_clicks ENABLE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS product_clicks_select_own ON public.product_clicks';
    EXECUTE 'CREATE POLICY product_clicks_select_own ON public.product_clicks FOR SELECT USING (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS product_clicks_insert_own ON public.product_clicks';
    EXECUTE 'CREATE POLICY product_clicks_insert_own ON public.product_clicks FOR INSERT WITH CHECK (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS product_clicks_update_own ON public.product_clicks';
    EXECUTE 'CREATE POLICY product_clicks_update_own ON public.product_clicks FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS product_clicks_delete_own ON public.product_clicks';
    EXECUTE 'CREATE POLICY product_clicks_delete_own ON public.product_clicks FOR DELETE USING (auth.uid() = user_id)';

    -- affiliate_conversions: RLS on, NO policy -> only the service/owner connection reads.
    EXECUTE 'ALTER TABLE public.affiliate_conversions ENABLE ROW LEVEL SECURITY';
END $$;
"""


DOWNGRADE_SQL = r"""
DROP INDEX IF EXISTS public.idx_affiliate_conversions_click;
DROP TABLE IF EXISTS public.affiliate_conversions;
DROP INDEX IF EXISTS public.idx_product_clicks_product;
DROP INDEX IF EXISTS public.idx_product_clicks_user_created;
DROP TABLE IF EXISTS public.product_clicks;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
