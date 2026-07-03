"""Service layer for closet/clothing items operations."""

from __future__ import annotations

import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session, selectinload

from app.models import ClothingItem
from app.services.enrichment import normalize_category

logger = logging.getLogger(__name__)


def _user_edited_attributes(category: str | None, brand: str | None, color: str | None) -> dict:
    """Seed attributes_json with provenance='user_edited' for manually-typed fields.

    A manual create is the user asserting these values, so they are authoritative: the
    async enricher fills the REST as 'inferred' and never overwrites these. Only non-empty
    fields are recorded (confidence is None — a human, not a model score)."""
    values = {"category": category, "brand": brand, "color_primary": color}
    attrs: dict = {}
    for key, v in values.items():
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        attrs[key] = {"value": v, "confidence": None, "provenance": "user_edited"}
    return attrs


def list_closet_items(
    db: Session,
    user_id: UUID,
    include_tags: bool = False,  # Ignored for backward compatibility, no longer used
) -> List[ClothingItem]:
    """List all clothing items for a user with images eagerly loaded.
    
    Uses selectinload to fetch all ItemImage relationships in a single query,
    avoiding N+1 queries when checking for primary images.
    
    Args:
        db: Database session
        user_id: UUID of the user
        include_tags: Ignored (kept for backward compatibility)
        
    Returns:
        List of ClothingItem SQLAlchemy models with images relationship loaded,
        ordered by created_at DESC (newest first)
    """
    items = (
        db.query(ClothingItem)
        .filter(ClothingItem.user_id == user_id)
        .options(selectinload(ClothingItem.images))  # Always load images
        .order_by(ClothingItem.created_at.desc())
        .all()
    )
    return items


def create_closet_item(
    db: Session,
    user_id: UUID,
    name: str,
    category: str | None = None,
    brand: str | None = None,
    color: str | None = None,
    image_url: str | None = None,
) -> ClothingItem:
    """Create a new clothing item for a user.
    
    Args:
        db: Database session
        user_id: UUID of the user
        name: Item name (required)
        category: Item category (optional)
        brand: Item brand (optional)
        color: Item color (optional, stored in color_primary)
        image_url: Image URL (optional)
        
    Returns:
        Created ClothingItem SQLAlchemy model
    """
    # Branch B: fold legacy category aliases so manual entries land canonical, and seed
    # provenance='user_edited' for the typed fields (the async enricher fills the rest as
    # 'inferred' and never overwrites these). Embedding + full Tier-1/2 enrichment run in
    # the background task the route schedules after this returns.
    category = normalize_category(category)
    item = ClothingItem(
        user_id=user_id,
        name=name,
        category=category,
        brand=brand,
        color_primary=color,  # Map color input to color_primary field
        image_url=image_url,
        attributes_json=_user_edited_attributes(category, brand, color),
    )

    db.add(item)
    db.commit()
    db.refresh(item)
    
    logger.info(f"Created clothing item {item.id} for user {user_id}")
    
    return item


def get_closet_item_by_id(
    db: Session,
    user_id: UUID,
    item_id: UUID,
) -> Optional[ClothingItem]:
    """Get a single clothing item by ID for a user with images eagerly loaded.
    
    Uses selectinload to fetch images relationship in a single query,
    avoiding N+1 queries.
    
    Args:
        db: Database session
        user_id: UUID of the user (for security check)
        item_id: UUID of the clothing item
        
    Returns:
        ClothingItem SQLAlchemy model with images relationship loaded,
        or None if not found or doesn't belong to user
    """
    item = (
        db.query(ClothingItem)
        .filter(ClothingItem.id == item_id)
        .filter(ClothingItem.user_id == user_id)  # Security: ensure user owns the item
        .options(
            selectinload(ClothingItem.images),  # Eagerly load images
        )
        .first()
    )
    return item


def update_closet_item(
    db: Session,
    user_id: UUID,
    item_id: UUID,
    name: Optional[str] = None,
    category: Optional[str] = None,
    brand: Optional[str] = None,
    color: Optional[str] = None,
    image_url: Optional[str] = None,
    commit: bool = True,
) -> Optional[ClothingItem]:
    """Update a clothing item with partial fields.
    
    Only updates fields that are provided (not None).
    Updates the updated_at timestamp automatically.
    
    Args:
        db: Database session
        user_id: UUID of the user (for security check)
        item_id: UUID of the clothing item
        name: New item name (optional)
        category: New category (optional)
        brand: New brand (optional)
        color: New color (stored in color_primary) (optional)
        image_url: New image URL (optional)
        commit: If True, commit the transaction (default: True). Set False for atomic operations.
        
    Returns:
        Updated ClothingItem SQLAlchemy model,
        or None if not found or doesn't belong to user
        
    Raises:
        ValueError: If name is provided but empty after stripping
    """
    # Get item and verify ownership
    item = (
        db.query(ClothingItem)
        .filter(ClothingItem.id == item_id)
        .filter(ClothingItem.user_id == user_id)
        .first()
    )
    
    if not item:
        return None
    
    # Validate name if provided
    if name is not None:
        name = name.strip()
        if not name:
            raise ValueError("Item name cannot be empty")
        item.name = name
    
    # Update other fields if provided
    if category is not None:
        item.category = category
    if brand is not None:
        item.brand = brand
    if color is not None:
        item.color_primary = color
    if image_url is not None:
        item.image_url = image_url
    
    # updated_at is automatically updated by SQLAlchemy's onupdate
    
    if commit:
        db.commit()
        db.refresh(item)
    
    logger.info(f"Updated clothing item {item.id} for user {user_id}")
    
    return item

