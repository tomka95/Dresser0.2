import uuid

from datetime import datetime

from sqlalchemy import (
    Column, String, DateTime, Boolean, ForeignKey, Text, Integer, BigInteger,
    Float, UniqueConstraint, CheckConstraint, Table, Index, JSON,
)
from sqlalchemy.dialects.postgresql import JSONB, ARRAY as PG_ARRAY
from sqlalchemy.orm import relationship

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


    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    email = Column(String, unique=True, index=True, nullable=False)

    hashed_password = Column(String, nullable=False)

    display_name = Column(String, nullable=True)

    google_sub = Column(String, unique=True, index=True, nullable=True)

    full_name = Column(String, nullable=True)

    avatar_url = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    gmail_sync_completed_at = Column(DateTime(timezone=True), nullable=True)


    clothing_items = relationship("ClothingItem", back_populates="user", cascade="all, delete-orphan")

    google_account = relationship("GoogleAccount", back_populates="user", uselist=False)




class ClothingItem(Base):

    __tablename__ = "clothing_items"
    
    __table_args__ = (
        Index('idx_clothing_items_user_id', 'user_id'),
        Index('idx_clothing_items_user_id_created_at', 'user_id', 'created_at'),
    )


    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)


    name = Column(String, nullable=False)

    category = Column(String, nullable=True)

    sub_category = Column(String, nullable=True)

    color_primary = Column(String, nullable=True)

    color_secondary = Column(String, nullable=True)

    brand = Column(String, nullable=True)

    size = Column(String, nullable=True)

    image_url = Column(Text, nullable=True)

    analysis_raw = Column(_jsonb(), nullable=True)  # raw analysis/tags payload (jsonb in DB)

    # Tagging / scoring columns that exist live in Supabase. Arrays default to []
    # and attributes_json to {} (server defaults owned by the migration).
    tags = Column(_text_array(), nullable=False, default=list)

    colors = Column(_text_array(), nullable=False, default=list)

    style_tags = Column(_text_array(), nullable=False, default=list)

    tag_scores = Column(_jsonb(), nullable=True)

    color_scores = Column(_jsonb(), nullable=True)

    attributes_json = Column(_jsonb(), nullable=False, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


    user = relationship("User", back_populates="clothing_items")

    images = relationship("ItemImage", back_populates="clothing_item", cascade="all, delete-orphan")




class ItemImage(Base):

    __tablename__ = "item_images"
    
    __table_args__ = (
        Index('idx_item_images_clothing_item_id', 'clothing_item_id'),
        Index('idx_item_images_clothing_item_id_is_primary', 'clothing_item_id', 'is_primary'),
    )


    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    clothing_item_id = Column(GUID(), ForeignKey("clothing_items.id", ondelete="CASCADE"), nullable=False, index=True)

    image_url = Column(Text, nullable=False)

    type = Column(String, nullable=True)

    is_primary = Column(Boolean, default=False)


    created_at = Column(DateTime, default=datetime.utcnow)


    clothing_item = relationship("ClothingItem", back_populates="images")




class GoogleAccount(Base):

    __tablename__ = "google_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)

    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)

    google_sub = Column(String, index=True, nullable=False)

    email = Column(String, index=True, nullable=False)

    access_token = Column(String, nullable=False)

    refresh_token = Column(String, nullable=True)

    scope = Column(String, nullable=True)

    token_expiry = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="google_account")




# --- Tables that exist live but were previously unmodeled in the ORM ---------
# Modeled here so the ORM and the Alembic baseline agree with the real database.
# These are not yet wired into any endpoint; they document the live schema and
# unblock future features (preferences, weather caching, waitlist).

class UserPreference(Base):

    __tablename__ = "user_preferences"

    __table_args__ = (
        UniqueConstraint("user_id", "key", name="user_preferences_user_id_key_unique"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="user_preferences_confidence_check"),
        CheckConstraint("source IN ('chat', 'manual', 'inferred')", name="user_preferences_source_check"),
        Index("idx_user_preferences_user_id", "user_id"),
        Index("idx_user_preferences_user_id_key", "user_id", "key"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    # NOTE: user_id is TEXT live (not a FK to users.id) -- modeled as-is.
    user_id = Column(Text, nullable=False)

    key = Column(Text, nullable=False)

    value = Column(Text, nullable=False)

    confidence = Column(Float, nullable=False, default=0.6)

    source = Column(Text, nullable=False, default="chat")

    evidence_text = Column(Text, nullable=True)

    last_seen_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)




class UserPreferenceEvent(Base):

    __tablename__ = "user_preference_events"

    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="user_preference_events_confidence_check"),
        CheckConstraint("source IN ('chat', 'manual', 'inferred')", name="user_preference_events_source_check"),
        Index("idx_user_preference_events_user_key_time", "user_id", "key", "created_at"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    user_id = Column(Text, nullable=False)

    key = Column(Text, nullable=False)

    value = Column(Text, nullable=False)

    confidence = Column(Float, nullable=False)

    source = Column(Text, nullable=False)

    evidence_text = Column(Text, nullable=True)

    message_id = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)




class WeatherCache(Base):

    __tablename__ = "weather_cache"

    __table_args__ = (
        Index("idx_weather_cache_expires", "expires_at"),
        Index("idx_weather_cache_lookup", "provider", "lat", "lon", "timezone", "start_at", "end_at"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    provider = Column(Text, nullable=False)

    lat = Column(Float, nullable=False)

    lon = Column(Float, nullable=False)

    timezone = Column(Text, nullable=False)

    start_at = Column(DateTime(timezone=True), nullable=False)

    end_at = Column(DateTime(timezone=True), nullable=False)

    payload = Column(_jsonb(), nullable=False)

    fetched_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    expires_at = Column(DateTime(timezone=True), nullable=False)




class Waitlist(Base):

    __tablename__ = "waitlist"

    __table_args__ = (
        Index("idx_waitlist_email", "email"),
        Index("idx_waitlist_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    email = Column(String, unique=True, nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

