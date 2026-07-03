"""AI Stylist data substrate: universal garment schema + item embeddings + style_* tables (Wave S0, Branch A)

Revision ID: 0018_stylist_data_substrate
Revises: 0017_clothing_items_generation_status
Create Date: 2026-07-03

Wave S0 Branch A lays the DB substrate the AI Stylist (Branches B/C) drops onto.
Pure foundation: schema only, no behavior change, nothing here populates the new
columns/tables (Branch B enriches, Branch C instruments). Ship-alone safe.

Eight pieces, ordered (order matters — extension first, FK-target tables before
their referrers), all owned by Alembic (no live-only DDL):

  0. CREATE EXTENSION "vector" (pgvector 0.8.0, available on the instance) FIRST —
     item_embeddings.embedding depends on it.

  1. clothing_items — Tier-1/2/4 universal garment columns. ALL nullable or
     constant-DEFAULT (is_favorite=false, wear_count=0), so Postgres uses a fast
     default and never rewrites/locks the populated table. text + named CHECK for
     the "enum" columns (the 0006 user_preferences.source pattern; autogenerate does
     not diff CHECKs, so they never drift).

       * category   : NEW named CHECK. SUPERSET of the canonical 12 + the legacy
                      aliases 'shoes','accessories','other' that EXIST in live data
                      (verified: rows carry 'shoes'/'accessories') and that the
                      current 7-enum extractor/PATCH validator still emit. A strict
                      12-only CHECK would reject those rows / break the edit endpoint,
                      violating "no behavior change". Branch B normalizes
                      shoes->footwear, accessories->accessory, other->canonical, then
                      a later migration can tighten this CHECK to the 12.
       * subcategory: reuses the EXISTING (dead, all-NULL) sub_category column as the
                      canonical carrier — no rename (keeps ORM/reflection parity), no
                      duplicate column. 72-value CHECK derived from Fashionpedia.
       * color_primary_hex, pattern, material, fit_silhouette, fit_rise (text)
       * formality int + CHECK 1..5 ; warmth int + CHECK 1..3
       * seasons text[] ; occasions text[]   (nullable; NULL = unknown, {} = none)
       * Tier-2: length, neckline, sleeve_length, heel_height (text)
       * Tier-4 lifecycle: acquired_date date, condition text+CHECK, is_favorite bool
         NOT NULL DEFAULT false, archived_at timestamptz, wear_count int NOT NULL
         DEFAULT 0, last_worn_at timestamptz.

  2. attributes_json — re-purposed as the per-field provenance+confidence carrier
     (shape documented in the column comment). Not populated here (Branch B). Was an
     always-{} unused column; verified 0 non-empty rows.

  3. DROP the dead tagging/scoring columns tags, colors, style_tags, tag_scores,
     color_scores (verified never written/read; 0 non-empty rows). DROP COLUMN also
     drops their GIN indexes. analysis_raw + attributes_json (and their GINs) stay.

  4. item_embeddings — pgvector side table (chosen over a column on clothing_items:
     re-embedding/model-versioning without touching the hot closet row, dedicated ANN
     index + RLS, keeps SELECT * on clothing_items narrow). embedding vector(768)
     matches the documented EMBEDDING_MODEL default (text-embedding-004). NO ANN index
     here — Branch B builds hnsw/ivfflat AFTER it bulk-populates (best practice; also
     keeps this migration's `alembic check` free of an exotic opclass index to
     round-trip). Per-user RLS via user_id.

  5. style_events / style_profiles / style_preferences / preference_signals — the
     Stylist substrate tables (Branch C writes events/signals; S1 distills profiles;
     style_preferences supersedes the dropped user_preferences). All UUID user_id ->
     users(id) with per-user RLS (auth.uid() = user_id, no ::text cast).
     preference_signals is created AFTER style_events (FK event_id -> style_events).

  6. Per-user RLS on all 5 new tables (guarded by the Supabase auth schema, matching
     0006/0014: DROP POLICY IF EXISTS + CREATE, all four verbs, auth.uid() = user_id).

  7. DROP the legacy user_preferences + user_preference_events (verified 0 rows, no
     live reader/writer, TEXT user_id debt) and their trigger function — superseded by
     style_preferences / preference_signals.

Downgrade fully reverses: recreates the two legacy pref tables (+ their RLS, trigger
function/trigger), re-adds the five dropped dead columns (+ GIN indexes), drops the
new columns/constraints/tables, and drops the vector extension.

Postgres/Supabase-specific (uuid, jsonb, vector, RLS) by design. The optional
LOCAL_DB=sqlite dev/test mode never runs Alembic migrations (it builds the schema
from app/models.py via create_all; the Vector type maps to a SQLite fallback there).
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0018_stylist_data_substrate"
down_revision = "0017_clothing_items_generation_status"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
-- ============================================================================
-- (0) pgvector extension FIRST (item_embeddings.embedding depends on it).
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS "vector";

-- ============================================================================
-- (1) clothing_items: Tier-1/2/4 universal garment columns.
--     All nullable or constant-DEFAULT -> fast default, no table rewrite/lock.
-- ============================================================================
ALTER TABLE public.clothing_items
    ADD COLUMN IF NOT EXISTS color_primary_hex text,
    ADD COLUMN IF NOT EXISTS pattern           text,
    ADD COLUMN IF NOT EXISTS material          text,
    ADD COLUMN IF NOT EXISTS fit_silhouette    text,
    ADD COLUMN IF NOT EXISTS fit_rise          text,
    ADD COLUMN IF NOT EXISTS formality         integer,
    ADD COLUMN IF NOT EXISTS warmth            integer,
    ADD COLUMN IF NOT EXISTS seasons           text[],
    ADD COLUMN IF NOT EXISTS occasions         text[],
    ADD COLUMN IF NOT EXISTS length            text,
    ADD COLUMN IF NOT EXISTS neckline          text,
    ADD COLUMN IF NOT EXISTS sleeve_length     text,
    ADD COLUMN IF NOT EXISTS heel_height       text,
    ADD COLUMN IF NOT EXISTS acquired_date     date,
    ADD COLUMN IF NOT EXISTS condition         text,
    ADD COLUMN IF NOT EXISTS is_favorite       boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS archived_at       timestamptz,
    ADD COLUMN IF NOT EXISTS wear_count        integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_worn_at      timestamptz;

-- Named CHECKs (guarded; idempotent). Not diffed by autogenerate.
DO $$
BEGIN
    -- category: canonical 12 + grandfathered legacy aliases (shoes/accessories/other)
    -- present in live data / still emitted by the current 7-enum path. NULL allowed.
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'public' AND table_name = 'clothing_items'
          AND constraint_name = 'clothing_items_category_check'
    ) THEN
        ALTER TABLE public.clothing_items ADD CONSTRAINT clothing_items_category_check
            CHECK (category IS NULL OR category IN (
                'top','bottom','dress','outerwear','footwear','bag','accessory',
                'activewear','swim','lounge_underwear','suiting','jewelry',
                'shoes','accessories','other'));
    END IF;

    -- subcategory (reuses the existing all-NULL sub_category column). 72 values.
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'public' AND table_name = 'clothing_items'
          AND constraint_name = 'clothing_items_sub_category_check'
    ) THEN
        ALTER TABLE public.clothing_items ADD CONSTRAINT clothing_items_sub_category_check
            CHECK (sub_category IS NULL OR sub_category IN (
                -- top
                't_shirt','tank_top','blouse','shirt','polo','sweater','hoodie','cardigan',
                -- bottom
                'jeans','trousers','chinos','shorts','sweatpants','skirt_mini','skirt_midi','leggings',
                -- dress
                'mini_dress','midi_dress','maxi_dress','gown','shirt_dress',
                -- outerwear
                'jacket','denim_jacket','leather_jacket','blazer','coat','trench_coat','parka','vest',
                -- footwear
                'sneaker','boot','ankle_boot','heel','loafer','oxford','sandal','flat',
                -- bag
                'tote_bag','crossbody_bag','shoulder_bag','backpack','clutch','belt_bag',
                -- accessory
                'belt','hat','cap','beanie','scarf','gloves','sunglasses','tie','watch',
                -- activewear
                'sports_bra','athletic_shorts','joggers','track_jacket',
                -- swim
                'bikini','one_piece_swimsuit','swim_trunks',
                -- lounge_underwear
                'bra','underwear','boxers','pajamas','robe','lingerie',
                -- suiting
                'suit','suit_jacket','suit_trousers',
                -- jewelry
                'necklace','bracelet','earrings','ring'));
    END IF;

    -- formality 1..5
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'public' AND table_name = 'clothing_items'
          AND constraint_name = 'clothing_items_formality_check'
    ) THEN
        ALTER TABLE public.clothing_items ADD CONSTRAINT clothing_items_formality_check
            CHECK (formality IS NULL OR (formality >= 1 AND formality <= 5));
    END IF;

    -- warmth 1..3
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'public' AND table_name = 'clothing_items'
          AND constraint_name = 'clothing_items_warmth_check'
    ) THEN
        ALTER TABLE public.clothing_items ADD CONSTRAINT clothing_items_warmth_check
            CHECK (warmth IS NULL OR (warmth >= 1 AND warmth <= 3));
    END IF;

    -- condition lifecycle
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'public' AND table_name = 'clothing_items'
          AND constraint_name = 'clothing_items_condition_check'
    ) THEN
        ALTER TABLE public.clothing_items ADD CONSTRAINT clothing_items_condition_check
            CHECK (condition IS NULL OR condition IN
                   ('new','like_new','good','fair','worn','damaged'));
    END IF;
END $$;

-- ============================================================================
-- (2) attributes_json: re-purpose as the per-field provenance+confidence carrier.
--     Comment kept identical to app/models.py so `alembic check` sees no drift.
-- ============================================================================
COMMENT ON COLUMN public.clothing_items.attributes_json IS
    'Per-field provenance+confidence carrier (Branch B populates; empty {} until then). Shape: {field: {value, confidence: 0..1, provenance: extracted|user_edited|inferred|default}}. user_edited is never overwritten by extraction/inference.';

-- ============================================================================
-- (3) DROP the dead tagging/scoring columns (0 non-empty rows). DROP COLUMN also
--     drops their GIN indexes. analysis_raw + attributes_json (and GINs) stay.
-- ============================================================================
ALTER TABLE public.clothing_items
    DROP COLUMN IF EXISTS tags,
    DROP COLUMN IF EXISTS colors,
    DROP COLUMN IF EXISTS style_tags,
    DROP COLUMN IF EXISTS tag_scores,
    DROP COLUMN IF EXISTS color_scores;

-- ============================================================================
-- (4) item_embeddings: pgvector side table (Branch B populates + indexes).
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.item_embeddings (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id    uuid NOT NULL REFERENCES public.clothing_items(id) ON DELETE CASCADE,
    user_id    uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    embedding  vector(768) NOT NULL,
    model      text NOT NULL,
    dim        integer NOT NULL,
    version    integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT item_embeddings_item_id_model_version_key UNIQUE (item_id, model, version)
);
-- user_id lookups (item_id is served by the UNIQUE index's leftmost prefix). The ANN
-- (hnsw/ivfflat) index on `embedding` is intentionally deferred to Branch B.
CREATE INDEX IF NOT EXISTS idx_item_embeddings_user_id
    ON public.item_embeddings USING btree (user_id);

-- ============================================================================
-- (5) style_events: interaction event log (Branch C writes).
--     Per-event detail (dwell_ms, reason_chips, feed_position, weather, occasion,
--     ...) lives under the `properties` jsonb — no dedicated columns for those.
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.style_events (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    event_type  text NOT NULL,
    item_id     uuid REFERENCES public.clothing_items(id) ON DELETE SET NULL,
    entity_type text,
    entity_id   text,
    source      text,
    properties  jsonb NOT NULL DEFAULT '{}'::jsonb,
    session_id  uuid,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_style_events_user_created_at
    ON public.style_events USING btree (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_style_events_user_event_type
    ON public.style_events USING btree (user_id, event_type);
CREATE INDEX IF NOT EXISTS idx_style_events_item_id
    ON public.style_events USING btree (item_id);

-- ============================================================================
-- (6) style_profiles: distilled per-user style profile (one row per user; S1).
--     Two distinct concerns, two columns: `facts` = L1 hard constraints/sizes
--     (inviolable, cheaply + separately readable by the outfit composer);
--     `narrative_blob` = the distilled prose profile. `summary` = short headline.
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.style_profiles (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    facts          jsonb NOT NULL DEFAULT '{}'::jsonb,
    narrative_blob jsonb NOT NULL DEFAULT '{}'::jsonb,
    summary        text,
    version        integer NOT NULL DEFAULT 1,
    distilled_at   timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT style_profiles_user_id_key UNIQUE (user_id)
);

-- ============================================================================
-- (7) style_preferences: structured per-user prefs (supersedes user_preferences).
--     `dimension` = the preference axis (color/silhouette/formality/brand/...).
--     `polarity` = like|dislike|neutral. `evidence_count` / `example_item_ids`
--     back the pref with observed items. `evidence` free-text carrier flagged for
--     future field-level redaction. last_seen_at doubles as last_reinforced_at.
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.style_preferences (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    dimension        text NOT NULL,
    value            jsonb NOT NULL DEFAULT '{}'::jsonb,
    polarity         text,
    confidence       real,
    weight           real,
    evidence_count   integer NOT NULL DEFAULT 0,
    example_item_ids uuid[],
    source           text NOT NULL DEFAULT 'explicit',
    active           boolean NOT NULL DEFAULT true,
    evidence         text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    last_seen_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT style_preferences_user_id_dimension_key UNIQUE (user_id, dimension),
    CONSTRAINT style_preferences_confidence_check
        CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CONSTRAINT style_preferences_polarity_check
        CHECK (polarity IS NULL OR polarity IN ('like','dislike','neutral')),
    CONSTRAINT style_preferences_source_check
        CHECK (source IN ('explicit','inferred','onboarding','imported'))
);

-- ============================================================================
-- (8) preference_signals: raw signals feeding distillation (append-only).
--     `polarity` = like|dislike|neutral. `weight` = signal strength.
--     `evidence_ref` = freeform pointer (message_id / event_id / 'onboarding').
--     FK event_id -> style_events, so it is created AFTER style_events.
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.preference_signals (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    signal_type  text NOT NULL,
    key          text,
    value        jsonb,
    polarity     text,
    item_id      uuid REFERENCES public.clothing_items(id) ON DELETE SET NULL,
    event_id     uuid REFERENCES public.style_events(id) ON DELETE SET NULL,
    evidence_ref text,
    weight       real,
    source       text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT preference_signals_polarity_check
        CHECK (polarity IS NULL OR polarity IN ('like','dislike','neutral')),
    CONSTRAINT preference_signals_source_check
        CHECK (source IS NULL OR source IN
               ('onboarding','chat_explicit','chat_inferred','behavior','outfit_feedback'))
);
CREATE INDEX IF NOT EXISTS idx_preference_signals_user_created_at
    ON public.preference_signals USING btree (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_preference_signals_user_signal_type
    ON public.preference_signals USING btree (user_id, signal_type);
CREATE INDEX IF NOT EXISTS idx_preference_signals_event_id
    ON public.preference_signals USING btree (event_id);

-- ============================================================================
-- Per-user RLS on all 5 new tables (guarded: requires the Supabase auth schema).
-- user_id is UUID -> compare auth.uid() directly, no ::text cast (0006/0014 pattern).
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
        'item_embeddings','style_events','style_profiles',
        'style_preferences','preference_signals'
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
END $$;

-- ============================================================================
-- (9) DROP the legacy, dead, superseded preference tables (0 rows) + trigger fn.
--     DROP TABLE cascades their RLS policies, indexes, and the BEFORE UPDATE trigger.
-- ============================================================================
DROP TABLE IF EXISTS public.user_preference_events;
DROP TABLE IF EXISTS public.user_preferences;
DROP FUNCTION IF EXISTS public.update_user_preferences_updated_at();
"""


DOWNGRADE_SQL = r"""
-- Reverse of (9): recreate the legacy pref tables, their trigger fn/trigger, RLS. ---
CREATE TABLE IF NOT EXISTS public.user_preferences (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       text NOT NULL,
    key           text NOT NULL,
    value         text NOT NULL,
    confidence    real NOT NULL DEFAULT 0.6 CHECK (confidence >= 0 AND confidence <= 1),
    source        text NOT NULL DEFAULT 'chat' CHECK (source IN ('chat', 'manual', 'inferred')),
    evidence_text text,
    last_seen_at  timestamptz NOT NULL DEFAULT now(),
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT user_preferences_user_id_key_unique UNIQUE (user_id, key)
);
CREATE INDEX IF NOT EXISTS idx_user_preferences_user_id ON public.user_preferences USING btree (user_id);
CREATE INDEX IF NOT EXISTS idx_user_preferences_user_id_key ON public.user_preferences USING btree (user_id, key);

CREATE TABLE IF NOT EXISTS public.user_preference_events (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       text NOT NULL,
    key           text NOT NULL,
    value         text NOT NULL,
    confidence    real NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    source        text NOT NULL CHECK (source IN ('chat', 'manual', 'inferred')),
    evidence_text text,
    message_id    text,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_user_preference_events_user_key_time
    ON public.user_preference_events USING btree (user_id, key, created_at DESC);

CREATE OR REPLACE FUNCTION public.update_user_preferences_updated_at()
    RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO ''
AS $function$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$function$;
DROP TRIGGER IF EXISTS trigger_update_user_preferences_updated_at ON public.user_preferences;
CREATE TRIGGER trigger_update_user_preferences_updated_at
    BEFORE UPDATE ON public.user_preferences
    FOR EACH ROW
    EXECUTE FUNCTION public.update_user_preferences_updated_at();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) THEN
        RAISE NOTICE 'auth.users absent; skipping legacy-pref RLS restore.';
        RETURN;
    END IF;
    -- user_id is TEXT here -> ::text cast (the legacy debt these tables carry).
    EXECUTE 'ALTER TABLE public.user_preferences ENABLE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS user_preferences_select_own ON public.user_preferences';
    EXECUTE 'CREATE POLICY user_preferences_select_own ON public.user_preferences FOR SELECT USING (auth.uid()::text = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS user_preferences_insert_own ON public.user_preferences';
    EXECUTE 'CREATE POLICY user_preferences_insert_own ON public.user_preferences FOR INSERT WITH CHECK (auth.uid()::text = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS user_preferences_update_own ON public.user_preferences';
    EXECUTE 'CREATE POLICY user_preferences_update_own ON public.user_preferences FOR UPDATE USING (auth.uid()::text = user_id) WITH CHECK (auth.uid()::text = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS user_preferences_delete_own ON public.user_preferences';
    EXECUTE 'CREATE POLICY user_preferences_delete_own ON public.user_preferences FOR DELETE USING (auth.uid()::text = user_id)';

    EXECUTE 'ALTER TABLE public.user_preference_events ENABLE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS user_preference_events_select_own ON public.user_preference_events';
    EXECUTE 'CREATE POLICY user_preference_events_select_own ON public.user_preference_events FOR SELECT USING (auth.uid()::text = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS user_preference_events_insert_own ON public.user_preference_events';
    EXECUTE 'CREATE POLICY user_preference_events_insert_own ON public.user_preference_events FOR INSERT WITH CHECK (auth.uid()::text = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS user_preference_events_update_own ON public.user_preference_events';
    EXECUTE 'CREATE POLICY user_preference_events_update_own ON public.user_preference_events FOR UPDATE USING (auth.uid()::text = user_id) WITH CHECK (auth.uid()::text = user_id)';
    EXECUTE 'DROP POLICY IF EXISTS user_preference_events_delete_own ON public.user_preference_events';
    EXECUTE 'CREATE POLICY user_preference_events_delete_own ON public.user_preference_events FOR DELETE USING (auth.uid()::text = user_id)';
END $$;

-- Reverse of (5)-(8): drop the new Stylist tables (cascades their RLS + indexes). --
-- preference_signals first (FK -> style_events).
DROP TABLE IF EXISTS public.preference_signals;
DROP TABLE IF EXISTS public.style_preferences;
DROP TABLE IF EXISTS public.style_profiles;
DROP TABLE IF EXISTS public.style_events;

-- Reverse of (4): drop item_embeddings, then the extension (no dependents remain). -
DROP TABLE IF EXISTS public.item_embeddings;
DROP EXTENSION IF EXISTS "vector";

-- Reverse of (3): re-add the dropped dead columns + their GIN indexes + comments. --
ALTER TABLE public.clothing_items
    ADD COLUMN IF NOT EXISTS tags         text[] NOT NULL DEFAULT '{}'::text[],
    ADD COLUMN IF NOT EXISTS colors       text[] NOT NULL DEFAULT '{}'::text[],
    ADD COLUMN IF NOT EXISTS style_tags   text[] NOT NULL DEFAULT '{}'::text[],
    ADD COLUMN IF NOT EXISTS tag_scores   jsonb,
    ADD COLUMN IF NOT EXISTS color_scores jsonb;
COMMENT ON COLUMN public.clothing_items.colors IS 'Array of color tags for filtering (e.g., ["black", "navy"])';
COMMENT ON COLUMN public.clothing_items.style_tags IS 'Array of style tags for filtering (e.g., ["formal", "professional"])';
CREATE INDEX IF NOT EXISTS clothing_items_tags_gin ON public.clothing_items USING gin (tags);
CREATE INDEX IF NOT EXISTS clothing_items_colors_gin ON public.clothing_items USING gin (colors);
CREATE INDEX IF NOT EXISTS idx_clothing_items_colors_gin ON public.clothing_items USING gin (colors);
CREATE INDEX IF NOT EXISTS idx_clothing_items_style_tags_gin ON public.clothing_items USING gin (style_tags);

-- Reverse of (2): restore the original attributes_json comment. --------------------
COMMENT ON COLUMN public.clothing_items.attributes_json IS
    'JSONB object for future attributes (warmth, formality, modesty, fabric, etc.)';

-- Reverse of (1): drop the new CHECKs, then the new columns. -----------------------
ALTER TABLE public.clothing_items
    DROP CONSTRAINT IF EXISTS clothing_items_category_check,
    DROP CONSTRAINT IF EXISTS clothing_items_sub_category_check,
    DROP CONSTRAINT IF EXISTS clothing_items_formality_check,
    DROP CONSTRAINT IF EXISTS clothing_items_warmth_check,
    DROP CONSTRAINT IF EXISTS clothing_items_condition_check;

ALTER TABLE public.clothing_items
    DROP COLUMN IF EXISTS color_primary_hex,
    DROP COLUMN IF EXISTS pattern,
    DROP COLUMN IF EXISTS material,
    DROP COLUMN IF EXISTS fit_silhouette,
    DROP COLUMN IF EXISTS fit_rise,
    DROP COLUMN IF EXISTS formality,
    DROP COLUMN IF EXISTS warmth,
    DROP COLUMN IF EXISTS seasons,
    DROP COLUMN IF EXISTS occasions,
    DROP COLUMN IF EXISTS length,
    DROP COLUMN IF EXISTS neckline,
    DROP COLUMN IF EXISTS sleeve_length,
    DROP COLUMN IF EXISTS heel_height,
    DROP COLUMN IF EXISTS acquired_date,
    DROP COLUMN IF EXISTS condition,
    DROP COLUMN IF EXISTS is_favorite,
    DROP COLUMN IF EXISTS archived_at,
    DROP COLUMN IF EXISTS wear_count,
    DROP COLUMN IF EXISTS last_worn_at;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
