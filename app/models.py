import uuid

from datetime import datetime

from sqlalchemy import (
    Column, String, DateTime, Boolean, ForeignKey, Text, Integer, BigInteger,
    Float, Double, REAL, UniqueConstraint, CheckConstraint, Table, Index, JSON, text,
)
from sqlalchemy.dialects.postgresql import JSONB, ARRAY as PG_ARRAY
from sqlalchemy.orm import relationship


# Timestamp helper: the live DB uses `timestamp with time zone` for nearly every
# timestamp column. Use this so ORM metadata matches and autogenerate stays clean.
def _tstz(**kw):
    return DateTime(timezone=True)

from .db import Base, GUID


# --- Cross-dialect column helpers -------------------------------------------
# Production runs on PostgreSQL (Supabase); the optional LOCAL_DB=sqlite dev mode
# needs the same models to map cleanly. These mirror the intent of the GUID type:
# the real Postgres column type, with a portable SQLite fallback.
#
# Note: server-side defaults (e.g. ''{}''::text[], gen_random_uuid()) live in the
# Alembic baseline migration, which owns the schema. The Python-side defaults below
# keep ORM inserts working on both dialects without emitting Postgres-only DDL.
def _jsonb():
    return JSONB().with_variant(JSON(), "sqlite")


def _text_array():
    return PG_ARRAY(Text()).with_variant(JSON(), "sqlite")




class User(Base):

    __tablename__ = "users"

    # Live uses UNIQUE constraints (users_email_key / users_google_sub_key), not
    # the auto-named ix_* indexes that Column(unique=True, index=True) would create.
    __table_args__ = (
        UniqueConstraint("email", name="users_email_key"),
        UniqueConstraint("google_sub", name="users_google_sub_key"),
    )


    # Supabase Auth transition: public.users is a PROFILE table whose id equals the
    # corresponding auth.users id. The FK users.id -> auth.users(id) is added by
    # Alembic revision 0002 and is owned exclusively by that migration -- it is NOT
    # declared here, because auth.users is a Supabase/Postgres-only table that must
    # not be a mapped model (modeling it would break create_all() under the SQLite
    # dev/test mode). alembic/env.py::_include_object excludes this FK from
    # autogenerate so the ORM<->live parity stays clean. The uuid4 default remains
    # for the legacy custom-JWT signup path; Supabase-provisioned profiles set id
    # explicitly to the token's `sub`.
    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    # Live: email is `character varying`; the rest are `text`.
    email = Column(String, nullable=False)

    hashed_password = Column(Text, nullable=False)

    display_name = Column(Text, nullable=True)

    google_sub = Column(Text, nullable=True)

    full_name = Column(Text, nullable=True)

    avatar_url = Column(Text, nullable=True)

    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)

    gmail_sync_completed_at = Column(DateTime(timezone=True), nullable=True)


    clothing_items = relationship("ClothingItem", back_populates="user", cascade="all, delete-orphan")

    google_account = relationship("GoogleAccount", back_populates="user", uselist=False)




class ClothingItem(Base):

    __tablename__ = "clothing_items"

    __table_args__ = (
        Index('idx_clothing_items_user_id', 'user_id'),
        # created_at is DESC in the live DB (recent-first queries). Expressed via
        # text() so ORM metadata matches reflection and autogenerate stays clean.
        Index('idx_clothing_items_user_id_created_at', 'user_id', text('created_at DESC')),
        # GIN indexes present live. postgresql_using='gin' is honored on Postgres
        # and ignored on SQLite (create_all emits a plain index there).
        Index('clothing_items_tags_gin', 'tags', postgresql_using='gin'),
        Index('clothing_items_colors_gin', 'colors', postgresql_using='gin'),
        Index('idx_clothing_items_colors_gin', 'colors', postgresql_using='gin'),
        Index('clothing_items_analysis_raw_gin', 'analysis_raw', postgresql_using='gin'),
        Index('idx_clothing_items_style_tags_gin', 'style_tags', postgresql_using='gin'),
        Index('idx_clothing_items_attributes_json_gin', 'attributes_json', postgresql_using='gin'),
    )


    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)


    # Live: all of these are `text`.
    name = Column(Text, nullable=False)

    category = Column(Text, nullable=True)

    sub_category = Column(Text, nullable=True)

    color_primary = Column(Text, nullable=True)

    color_secondary = Column(Text, nullable=True)

    brand = Column(Text, nullable=True)

    size = Column(Text, nullable=True)

    image_url = Column(Text, nullable=True)

    analysis_raw = Column(_jsonb(), nullable=True)  # raw analysis/tags payload (jsonb in DB)

    # Tagging / scoring columns that exist live in Supabase. Arrays default to []
    # and attributes_json to {} (server defaults owned by the migration). Comments
    # mirror the live column comments so autogenerate sees no difference.
    tags = Column(_text_array(), nullable=False, default=list)

    colors = Column(_text_array(), nullable=False, default=list,
                    comment='Array of color tags for filtering (e.g., ["black", "navy"])')

    style_tags = Column(_text_array(), nullable=False, default=list,
                        comment='Array of style tags for filtering (e.g., ["formal", "professional"])')

    tag_scores = Column(_jsonb(), nullable=True)

    color_scores = Column(_jsonb(), nullable=True)

    attributes_json = Column(_jsonb(), nullable=False, default=dict,
                             comment='JSONB object for future attributes (warmth, formality, modesty, fabric, etc.)')

    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)

    updated_at = Column(_tstz(), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


    user = relationship("User", back_populates="clothing_items")

    images = relationship("ItemImage", back_populates="clothing_item", cascade="all, delete-orphan")




class ItemImage(Base):

    __tablename__ = "item_images"

    __table_args__ = (
        Index('idx_item_images_clothing_item_id', 'clothing_item_id'),
        # Partial index live: WHERE (is_primary = true). postgresql_where keeps the
        # ORM metadata identical to the DB.
        Index('idx_item_images_clothing_item_id_is_primary', 'clothing_item_id', 'is_primary',
              postgresql_where=text('is_primary = true')),
    )


    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    clothing_item_id = Column(GUID(), ForeignKey("clothing_items.id", ondelete="CASCADE"), nullable=False)

    image_url = Column(Text, nullable=False)

    type = Column(String, nullable=True)

    is_primary = Column(Boolean, default=False)


    # Live column is `timestamp WITHOUT time zone` (the one timestamp that is naive).
    created_at = Column(DateTime, default=datetime.utcnow)


    clothing_item = relationship("ClothingItem", back_populates="images")




class GoogleAccount(Base):

    __tablename__ = "google_accounts"

    __table_args__ = (
        UniqueConstraint("user_id", name="google_accounts_user_id_key"),
        Index("idx_google_accounts_email", "email"),
        Index("idx_google_accounts_google_sub", "google_sub"),
    )

    # Live column is bigint (bigserial).
    id = Column(BigInteger, primary_key=True, autoincrement=True)

    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Live: all of these are `text`.
    # google_sub / email are nullable as of migration 0005: the dedicated Gmail
    # ingest client requests gmail.readonly ONLY (no identity scopes), so the
    # connect flow has no Google subject id or email to record. Identity lives in
    # Supabase Auth; this table is purely the per-user Gmail token store.
    google_sub = Column(Text, nullable=True)

    email = Column(Text, nullable=True)

    # Stored ENCRYPTED at rest (AES-256-GCM, see app/core/token_crypto). Column
    # type is unchanged (text); only the contents are ciphertext now.
    access_token = Column(Text, nullable=False)

    refresh_token = Column(Text, nullable=True)

    scope = Column(Text, nullable=True)

    token_expiry = Column(_tstz(), nullable=True)

    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)

    updated_at = Column(_tstz(), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="google_account")




# --- Tables that exist live but were previously unmodeled in the ORM ---------
# Modeled here so the ORM and the Alembic baseline agree with the real database.
# These are not yet wired into any endpoint; they document the live schema and
# unblock future features (preferences, weather caching, waitlist).

class UserPreference(Base):

    __tablename__ = "user_preferences"

    __table_args__ = (
        UniqueConstraint("user_id", "key", name="user_preferences_user_id_key_unique"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence"),
        CheckConstraint("source IN ('chat', 'manual', 'inferred')", name="source"),
        Index("idx_user_preferences_user_id", "user_id"),
        Index("idx_user_preferences_user_id_key", "user_id", "key"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    # NOTE: user_id is TEXT live (not a FK to users.id) -- modeled as-is.
    user_id = Column(Text, nullable=False)

    key = Column(Text, nullable=False)

    value = Column(Text, nullable=False)

    confidence = Column(REAL, nullable=False, default=0.6)

    source = Column(Text, nullable=False, default="chat")

    evidence_text = Column(Text, nullable=True)

    last_seen_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)




class UserPreferenceEvent(Base):

    __tablename__ = "user_preference_events"

    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence"),
        CheckConstraint("source IN ('chat', 'manual', 'inferred')", name="source"),
        # created_at DESC live (recent-first). text() keeps metadata == reflection.
        Index("idx_user_preference_events_user_key_time", "user_id", "key", text("created_at DESC")),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    user_id = Column(Text, nullable=False)

    key = Column(Text, nullable=False)

    value = Column(Text, nullable=False)

    confidence = Column(REAL, nullable=False)

    source = Column(Text, nullable=False)

    evidence_text = Column(Text, nullable=True)

    message_id = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)




class WeatherCache(Base):

    __tablename__ = "weather_cache"

    __table_args__ = (
        Index("idx_weather_cache_expires", "expires_at"),
        Index("idx_weather_cache_lookup", "provider", "lat", "lon", "timezone", "start_at", "end_at"),
        {"comment": "Cache for weather API responses to reduce external API calls"},
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    provider = Column(Text, nullable=False, comment="Weather provider name (e.g., open_meteo)")

    # Live: double precision (float8).
    lat = Column(Double, nullable=False)

    lon = Column(Double, nullable=False)

    timezone = Column(Text, nullable=False)

    start_at = Column(DateTime(timezone=True), nullable=False)

    end_at = Column(DateTime(timezone=True), nullable=False)

    payload = Column(_jsonb(), nullable=False, comment="Cached WeatherForecast JSON payload")

    fetched_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    expires_at = Column(DateTime(timezone=True), nullable=False,
                        comment="When this cache entry expires (UTC)")




class Waitlist(Base):

    __tablename__ = "waitlist"

    __table_args__ = (
        UniqueConstraint("email", name="waitlist_email_key"),
        Index("idx_waitlist_email", "email"),
        # created_at DESC live (recent-first). text() keeps metadata == reflection.
        Index("idx_waitlist_created_at", text("created_at DESC")),
        {"comment": "Stores email addresses of users who joined the waitlist"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    email = Column(String, nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

