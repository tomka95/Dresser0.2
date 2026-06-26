"""baseline: reflect current live Supabase schema as revision 0

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-26

This is the baseline migration. It encodes the schema that ALREADY EXISTS in the
live Supabase Postgres database (introspected directly), folding in the intent of
the pre-Alembic migrations/*.sql files (closet indexes, gmail_sync_completed_at).

It is written to be a NO-OP against the live database:
  * every CREATE ... uses IF NOT EXISTS, so running `upgrade` against the live DB
    (where all objects already exist) changes nothing.
  * against a fresh Postgres, `upgrade` builds the complete schema.

For the existing live database the intended one-time operator action is:
    alembic stamp 0001_baseline
which records this revision as applied without executing any DDL.

Postgres-specific (text[], jsonb, gin indexes, gen_random_uuid()) by design: the
production database is Postgres. The optional LOCAL_DB=sqlite dev mode does not use
this migration (see app/db.py and README notes).
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
-- ============================ users ============================
CREATE TABLE IF NOT EXISTS users (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email                   varchar NOT NULL UNIQUE,
    hashed_password         text NOT NULL,
    display_name            text,
    created_at              timestamptz NOT NULL DEFAULT now(),
    google_sub              text UNIQUE,
    full_name               text,
    avatar_url              text,
    gmail_sync_completed_at timestamptz
);

-- ======================== clothing_items =======================
CREATE TABLE IF NOT EXISTS clothing_items (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            text NOT NULL,
    category        text,
    sub_category    text,
    color_primary   text,
    color_secondary text,
    brand           text,
    size            text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    image_url       text,
    tags            text[] NOT NULL DEFAULT '{}'::text[],
    colors          text[] NOT NULL DEFAULT '{}'::text[],
    analysis_raw    jsonb,
    tag_scores      jsonb,
    color_scores    jsonb,
    style_tags      text[] NOT NULL DEFAULT '{}'::text[],
    attributes_json jsonb NOT NULL DEFAULT '{}'::jsonb
);
COMMENT ON COLUMN clothing_items.colors IS 'Array of color tags for filtering (e.g., ["black", "navy"])';
COMMENT ON COLUMN clothing_items.style_tags IS 'Array of style tags for filtering (e.g., ["formal", "professional"])';
COMMENT ON COLUMN clothing_items.attributes_json IS 'JSONB object for future attributes (warmth, formality, modesty, fabric, etc.)';

CREATE INDEX IF NOT EXISTS idx_clothing_items_user_id ON clothing_items USING btree (user_id);
CREATE INDEX IF NOT EXISTS idx_clothing_items_user_id_created_at ON clothing_items USING btree (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS clothing_items_tags_gin ON clothing_items USING gin (tags);
CREATE INDEX IF NOT EXISTS clothing_items_colors_gin ON clothing_items USING gin (colors);
CREATE INDEX IF NOT EXISTS idx_clothing_items_colors_gin ON clothing_items USING gin (colors);
CREATE INDEX IF NOT EXISTS clothing_items_analysis_raw_gin ON clothing_items USING gin (analysis_raw);
CREATE INDEX IF NOT EXISTS idx_clothing_items_style_tags_gin ON clothing_items USING gin (style_tags);
CREATE INDEX IF NOT EXISTS idx_clothing_items_attributes_json_gin ON clothing_items USING gin (attributes_json);

-- ======================== google_accounts =====================
CREATE TABLE IF NOT EXISTS google_accounts (
    id            bigserial PRIMARY KEY,
    user_id       uuid NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    google_sub    text NOT NULL,
    email         text NOT NULL,
    access_token  text NOT NULL,
    refresh_token text,
    scope         text,
    token_expiry  timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_google_accounts_email ON google_accounts USING btree (email);
CREATE INDEX IF NOT EXISTS idx_google_accounts_google_sub ON google_accounts USING btree (google_sub);

-- ========================== item_images ========================
-- NOTE: item_images.id intentionally has NO server default; ids are generated
-- application-side (uuid4 via the ORM GUID type). created_at is timestamp WITHOUT tz.
CREATE TABLE IF NOT EXISTS item_images (
    id               uuid PRIMARY KEY,
    clothing_item_id uuid NOT NULL REFERENCES clothing_items(id) ON DELETE CASCADE,
    image_url        text NOT NULL,
    type             varchar,
    is_primary       boolean,
    created_at       timestamp
);
CREATE INDEX IF NOT EXISTS idx_item_images_clothing_item_id ON item_images USING btree (clothing_item_id);
CREATE INDEX IF NOT EXISTS idx_item_images_clothing_item_id_is_primary
    ON item_images USING btree (clothing_item_id, is_primary) WHERE (is_primary = true);

-- ======================== user_preferences =====================
CREATE TABLE IF NOT EXISTS user_preferences (
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
CREATE INDEX IF NOT EXISTS idx_user_preferences_user_id ON user_preferences USING btree (user_id);
CREATE INDEX IF NOT EXISTS idx_user_preferences_user_id_key ON user_preferences USING btree (user_id, key);

-- ===================== user_preference_events ==================
CREATE TABLE IF NOT EXISTS user_preference_events (
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
    ON user_preference_events USING btree (user_id, key, created_at DESC);

-- ========================= weather_cache =======================
CREATE TABLE IF NOT EXISTS weather_cache (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider   text NOT NULL,
    lat        double precision NOT NULL,
    lon        double precision NOT NULL,
    timezone   text NOT NULL,
    start_at   timestamptz NOT NULL,
    end_at     timestamptz NOT NULL,
    payload    jsonb NOT NULL,
    fetched_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);
COMMENT ON TABLE weather_cache IS 'Cache for weather API responses to reduce external API calls';
CREATE INDEX IF NOT EXISTS idx_weather_cache_expires ON weather_cache USING btree (expires_at);
CREATE INDEX IF NOT EXISTS idx_weather_cache_lookup
    ON weather_cache USING btree (provider, lat, lon, timezone, start_at, end_at);

-- ============================ waitlist =========================
CREATE TABLE IF NOT EXISTS waitlist (
    id         serial PRIMARY KEY,
    email      varchar NOT NULL UNIQUE,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE waitlist IS 'Stores email addresses of users who joined the waitlist';
CREATE INDEX IF NOT EXISTS idx_waitlist_email ON waitlist USING btree (email);
CREATE INDEX IF NOT EXISTS idx_waitlist_created_at ON waitlist USING btree (created_at DESC);
"""


# Reverse dependency order. Guarded so a partial/baseline-stamped DB downgrades cleanly.
DOWNGRADE_SQL = r"""
DROP TABLE IF EXISTS waitlist;
DROP TABLE IF EXISTS weather_cache;
DROP TABLE IF EXISTS user_preference_events;
DROP TABLE IF EXISTS user_preferences;
DROP TABLE IF EXISTS item_images;
DROP TABLE IF EXISTS google_accounts;
DROP TABLE IF EXISTS clothing_items;
DROP TABLE IF EXISTS users;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    # Intentionally destructive: only meaningful on a throwaway database. The
    # baseline is never expected to be downgraded against the live DB.
    op.execute(DOWNGRADE_SQL)
