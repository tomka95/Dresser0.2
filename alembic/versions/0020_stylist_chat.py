"""AI Stylist chat substrate: conversations + messages + saved outfits + usage/limits (Wave S2)

Revision ID: 0020_stylist_chat
Revises: 0019_item_embeddings_hnsw
Create Date: 2026-07-04

Wave S2 drops the chat vertical onto the S0/S1 substrate. Five tables:

  1. conversations   — one row per chat thread. Retention is a hard TTL column
                       (expires_at, server default now() + 90 days): the cleanup
                       path (persistence.sweep_expired_conversations) deletes the
                       caller's expired rows opportunistically on conversation
                       list/create, and every new message pushes expires_at forward
                       (rolling retention). ON DELETE CASCADE erases the messages.

  2. chat_messages   — the transcript. role CHECK ('user','assistant','tool');
                       tool_calls jsonb holds per-turn tool summaries (name, status,
                       latency — never raw user content beyond the message itself);
                       per-ASSISTANT-turn token counts + cost_usd land here (the
                       per-turn cost ledger; chat_usage below is the per-day rollup).
                       user_id is denormalized from the conversation (mirrors
                       item_embeddings) so RLS filters without a join.

  3. saved_outfits   — compose_outfit results the user kept. item_ids uuid[] refer
                       to the user's own clothing_items (validated server-side at
                       save; array FKs are not enforceable in PG). rationale = the
                       stylist's stored "why".

  4. chat_usage      — per-user per-DAY usage rollup: turns, tokens, cost. THE
                       free-tier quota ledger (checked before each turn) and the
                       cost dashboard source. UNIQUE(user_id, period_start); rows
                       are incremented via atomic upsert (cross-worker safe).

  5. chat_rate_windows — one row per user: fixed 60s window counter for the shared
                       (cross-worker) per-user rate limiter. Server-managed only:
                       RLS enabled with NO policies (owner/service writes; anon/
                       authenticated denied), mirroring product_image_cache.

RLS: conversations / chat_messages / saved_outfits / chat_usage get the full
0018-pattern per-user policies (all four verbs, auth.uid() = user_id, UUID compare
— no ::text cast), guarded by the Supabase auth schema. This is what makes the
agent's RLS-scoped connection (SET LOCAL role authenticated + request.jwt.claims)
an actual backstop: even a forgotten WHERE user_id cannot cross tenants.

Postgres/Supabase-specific (uuid, jsonb, uuid[], RLS) by design; the LOCAL_DB=sqlite
dev/test mode builds these tables from app/models.py via create_all().
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0020_stylist_chat"
down_revision = "0019_item_embeddings_hnsw"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
-- ============================================================================
-- (1) conversations
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.conversations (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    title      text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    -- Retention TTL: rolling window, pushed forward on every new message.
    expires_at timestamptz NOT NULL DEFAULT (now() + interval '90 days')
);
CREATE INDEX IF NOT EXISTS idx_conversations_user_id
    ON public.conversations USING btree (user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_expires_at
    ON public.conversations USING btree (expires_at);

-- ============================================================================
-- (2) chat_messages
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.chat_messages (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
    user_id         uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    role            text NOT NULL,
    content         text NOT NULL DEFAULT '',
    -- Per-turn tool activity summary: [{name, status, latency_ms, summary}].
    -- ids + counts only — never raw model arguments or other users' data.
    tool_calls      jsonb,
    -- Composed-outfit payload for assistant turns that produced one (item ids +
    -- slots + rationale), so the FE can re-render outfits from history.
    outfit_json     jsonb,
    model           text,
    input_tokens    integer NOT NULL DEFAULT 0,
    output_tokens   integer NOT NULL DEFAULT 0,
    cost_usd        numeric NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chat_messages_role_check
        CHECK (role IN ('user','assistant','tool'))
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation_created
    ON public.chat_messages USING btree (conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_chat_messages_user_id
    ON public.chat_messages USING btree (user_id);

-- ============================================================================
-- (3) saved_outfits
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.saved_outfits (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    title      text,
    item_ids   uuid[] NOT NULL,
    rationale  text,
    occasion   text,
    source     text NOT NULL DEFAULT 'chat',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT saved_outfits_source_check
        CHECK (source IN ('chat','composer'))
);
CREATE INDEX IF NOT EXISTS idx_saved_outfits_user_id
    ON public.saved_outfits USING btree (user_id);

-- ============================================================================
-- (4) chat_usage (per-user per-day rollup: the quota ledger)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.chat_usage (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    period_start  date NOT NULL,
    turns         integer NOT NULL DEFAULT 0,
    input_tokens  bigint NOT NULL DEFAULT 0,
    output_tokens bigint NOT NULL DEFAULT 0,
    cost_usd      numeric NOT NULL DEFAULT 0,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chat_usage_user_id_period_start_key UNIQUE (user_id, period_start)
);

-- ============================================================================
-- (5) chat_rate_windows (server-managed fixed-window rate limiter state)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.chat_rate_windows (
    user_id      uuid PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    window_start timestamptz NOT NULL,
    count        integer NOT NULL DEFAULT 0
);

-- ============================================================================
-- Per-user RLS (0018 pattern: guarded, all four verbs, auth.uid() = user_id).
-- chat_rate_windows is server-managed: RLS enabled with NO policies (deny-all
-- for anon/authenticated), mirroring product_image_cache.
-- ============================================================================
DO $$
DECLARE
    t text;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) THEN
        RAISE NOTICE 'auth.users absent; skipping per-user RLS (non-Supabase DB).';
        RETURN;
    END IF;

    FOREACH t IN ARRAY ARRAY[
        'conversations','chat_messages','saved_outfits','chat_usage'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_select_own', t);
        EXECUTE format('CREATE POLICY %I ON public.%I FOR SELECT USING (auth.uid() = user_id)',
                       t || '_select_own', t);
        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_insert_own', t);
        EXECUTE format('CREATE POLICY %I ON public.%I FOR INSERT WITH CHECK (auth.uid() = user_id)',
                       t || '_insert_own', t);
        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_update_own', t);
        EXECUTE format('CREATE POLICY %I ON public.%I FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id)',
                       t || '_update_own', t);
        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_delete_own', t);
        EXECUTE format('CREATE POLICY %I ON public.%I FOR DELETE USING (auth.uid() = user_id)',
                       t || '_delete_own', t);
    END LOOP;

    EXECUTE 'ALTER TABLE public.chat_rate_windows ENABLE ROW LEVEL SECURITY';
END $$;
"""


DOWNGRADE_SQL = r"""
-- Reverse creation order (chat_messages references conversations).
DROP TABLE IF EXISTS public.chat_rate_windows;
DROP TABLE IF EXISTS public.chat_usage;
DROP TABLE IF EXISTS public.saved_outfits;
DROP TABLE IF EXISTS public.chat_messages;
DROP TABLE IF EXISTS public.conversations;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
