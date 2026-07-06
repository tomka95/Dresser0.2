"""wardrobe_gap: user_wardrobe_gap (Wave F2)

Revision ID: 0024_wardrobe_gap
Revises: 0023_monetization
Create Date: 2026-07-06

The precomputed marginal-outfit-unlock signal for the shopping feed's ranker.

  user_wardrobe_gap : one row per (user, candidate product) written by the nightly
    wardrobe-gap job (scripts/dev_wardrobe_gap.py). Records how many wardrobe CONTEXTS
    (occasion × formality × warmth over the IL climate calendar) the product newly
    unlocks against what the user ALREADY owns (unlock_count), plus a gap_context jsonb
    the feed uses for the "unlocks N outfits" preview (which occasions/categories it
    fills + example owned-item ids). PER-USER RLS (auth.uid() = user_id), the 0018/0023
    pattern — a user's computed wardrobe gaps are their own.

    The job is pure CPU ($0 API): it reuses assemble_from_pool (app.services.stylist.compat)
    over the closet, no LLM. This table is the ONLY thing the feed reads for the gap signal
    at serve time (also $0 API). Nothing here references a payout/commission/affiliate field
    — those live only in app/monetization, structurally unreachable from the ranker.

Conventions reused from 0018/0022/0023: raw SQL via op.execute; CREATE TABLE IF NOT
EXISTS; inline PK/UNIQUE/REFERENCES so Postgres auto-names them to match the ORM naming
convention; RLS guarded on the Supabase auth schema.

Postgres/Supabase-specific. LOCAL_DB=sqlite dev/test never runs Alembic (create_all;
RLS skipped).
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0024_wardrobe_gap"
down_revision = "0023_monetization"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
-- ============================================================================
-- user_wardrobe_gap: precomputed marginal-outfit-unlock per (user, product).
--   One row per candidate; the nightly job upserts (user_id, product_id).
--   PER-USER RLS.
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.user_wardrobe_gap (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    -- CASCADE: a purged product drops its stale gap rows (unlike a click record,
    -- a gap row has no standalone meaning once the product is gone).
    product_id    uuid NOT NULL REFERENCES public.products(id) ON DELETE CASCADE,
    unlock_count  integer NOT NULL DEFAULT 0,
    -- Which occasions/categories the product fills + example owned-item ids for the
    -- feed's "unlocks N outfits" preview sheet. Shape written by app.ranking.gap.
    gap_context   jsonb NOT NULL DEFAULT '{}'::jsonb,
    computed_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT user_wardrobe_gap_user_product_key UNIQUE (user_id, product_id),
    CONSTRAINT user_wardrobe_gap_unlock_nonneg_check CHECK (unlock_count >= 0)
);
-- Feed read path: a user's candidates ordered by how many outfits they unlock.
CREATE INDEX IF NOT EXISTS idx_user_wardrobe_gap_user_unlock
    ON public.user_wardrobe_gap USING btree (user_id, unlock_count DESC);
-- Staleness sweep / per-user recompute.
CREATE INDEX IF NOT EXISTS idx_user_wardrobe_gap_user_computed
    ON public.user_wardrobe_gap USING btree (user_id, computed_at);

-- ============================================================================
-- RLS. Guarded on Supabase auth. Per-user (4 policies, auth.uid() = user_id),
-- the 0018/0023 pattern (UUID user_id, no ::text cast).
-- ============================================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) THEN
        RAISE NOTICE 'auth.users absent; skipping RLS on user_wardrobe_gap (non-Supabase DB).';
        RETURN;
    END IF;

    EXECUTE 'ALTER TABLE public.user_wardrobe_gap ENABLE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS user_wardrobe_gap_select_own ON public.user_wardrobe_gap';
    EXECUTE 'CREATE POLICY user_wardrobe_gap_select_own ON public.user_wardrobe_gap FOR SELECT USING (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS user_wardrobe_gap_insert_own ON public.user_wardrobe_gap';
    EXECUTE 'CREATE POLICY user_wardrobe_gap_insert_own ON public.user_wardrobe_gap FOR INSERT WITH CHECK (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS user_wardrobe_gap_update_own ON public.user_wardrobe_gap';
    EXECUTE 'CREATE POLICY user_wardrobe_gap_update_own ON public.user_wardrobe_gap FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS user_wardrobe_gap_delete_own ON public.user_wardrobe_gap';
    EXECUTE 'CREATE POLICY user_wardrobe_gap_delete_own ON public.user_wardrobe_gap FOR DELETE USING (auth.uid() = user_id)';
END $$;
"""


DOWNGRADE_SQL = r"""
DROP INDEX IF EXISTS public.idx_user_wardrobe_gap_user_computed;
DROP INDEX IF EXISTS public.idx_user_wardrobe_gap_user_unlock;
DROP TABLE IF EXISTS public.user_wardrobe_gap;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
