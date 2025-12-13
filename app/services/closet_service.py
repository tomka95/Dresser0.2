"""Service layer for closet/clothing items operations."""

import logging
from typing import List
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import ClothingItem

logger = logging.getLogger(__name__)


def list_closet_items(db: Session, user_id: UUID) -> List[ClothingItem]:
    """List all clothing items for a user.
    
    Args:
        db: Database session
        user_id: UUID of the user
        
    Returns:
        List of ClothingItem SQLAlchemy models, ordered by created_at DESC (newest first)
    """
    items = (
        db.query(ClothingItem)
        .filter(ClothingItem.user_id == user_id)
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
    item = ClothingItem(
        user_id=user_id,
        name=name,
        category=category,
        brand=brand,
        color_primary=color,  # Map color input to color_primary field
        image_url=image_url,
    )
    
    db.add(item)
    db.commit()
    db.refresh(item)
    
    logger.info(f"Created clothing item {item.id} for user {user_id}")
    
    return item

