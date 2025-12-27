import uuid

from datetime import datetime

from sqlalchemy import (

    Column, String, DateTime, Boolean, ForeignKey, Text, Integer, UniqueConstraint, Table, Index, JSON

)

from sqlalchemy.dialects.postgresql import UUID

from sqlalchemy.orm import relationship

from .db import Base




class User(Base):

    __tablename__ = "users"


    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

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


    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)


    name = Column(String, nullable=False)

    category = Column(String, nullable=True)

    sub_category = Column(String, nullable=True)

    color_primary = Column(String, nullable=True)

    color_secondary = Column(String, nullable=True)

    brand = Column(String, nullable=True)

    size = Column(String, nullable=True)

    image_url = Column(Text, nullable=True)

    analysis_raw = Column(JSON, nullable=True)  # JSON field for storing analysis/tags data

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


    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    clothing_item_id = Column(UUID(as_uuid=True), ForeignKey("clothing_items.id", ondelete="CASCADE"), nullable=False, index=True)

    image_url = Column(Text, nullable=False)

    type = Column(String, nullable=True)

    is_primary = Column(Boolean, default=False)


    created_at = Column(DateTime, default=datetime.utcnow)


    clothing_item = relationship("ClothingItem", back_populates="images")




class GoogleAccount(Base):

    __tablename__ = "google_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)

    google_sub = Column(String, index=True, nullable=False)

    email = Column(String, index=True, nullable=False)

    access_token = Column(String, nullable=False)

    refresh_token = Column(String, nullable=True)

    scope = Column(String, nullable=True)

    token_expiry = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="google_account")

