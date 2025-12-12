"""Service for saving clothing items extracted from emails to the database."""

from typing import Iterable, List, Union
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.models import ClothingItem, ItemImage


def save_email_items_for_user(
    db: Session,
    user_id: UUID,
    items: Iterable[Union[dict, object]],
) -> List[ClothingItem]:
    """
    Take structured clothing items extracted from an email and save them
    as ClothingItem rows linked to the given user_id.

    Args:
        db: Database session
        user_id: UUID of the user who owns these items
        items: Iterable of dicts or Pydantic models containing item data. Expected keys/attributes:
            - name (str, required): Item name
            - store or brand (str, optional): Store/brand name
            - price (float, optional): Item price (not stored in DB, used for deduplication)
            - image or image_url (str, optional): Image URL or alt text
            - category (str, optional): Item category
            - sub_category (str, optional): Item sub-category
            - color or color_primary (str, optional): Primary color
            - color_secondary (str, optional): Secondary color
            - size (str, optional): Item size
            - product_name (str, optional): Alternative name field

    Returns:
        List of created ClothingItem objects
    """
    created_items: List[ClothingItem] = []

    for item in items:
        # Convert Pydantic model to dict if needed
        if hasattr(item, 'dict'):
            item_dict = item.dict()
        elif hasattr(item, 'model_dump'):  # Pydantic v2
            item_dict = item.model_dump()
        elif isinstance(item, dict):
            item_dict = item
        else:
            # Try to access as attributes
            item_dict = {
                'name': getattr(item, 'name', None),
                'store': getattr(item, 'store', None),
                'brand': getattr(item, 'brand', None),
                'price': getattr(item, 'price', None),
                'image': getattr(item, 'image', None),
                'image_url': getattr(item, 'image_url', None),
                'category': getattr(item, 'category', None),
                'sub_category': getattr(item, 'sub_category', None),
                'color': getattr(item, 'color', None),
                'color_primary': getattr(item, 'color_primary', None),
                'color_secondary': getattr(item, 'color_secondary', None),
                'size': getattr(item, 'size', None),
                'product_name': getattr(item, 'product_name', None),
            }

        # Extract and normalize fields
        name = item_dict.get("name") or item_dict.get("product_name")
        if not name:
            # Skip items without a name
            continue

        # Normalize name
        name = name.strip()
        if not name:
            continue

        # Extract brand/store (prefer brand, fallback to store)
        brand = item_dict.get("brand") or item_dict.get("store")
        if brand:
            brand = brand.strip()
            if not brand:
                brand = None

        # Extract price (used for deduplication, not stored in DB)
        price = item_dict.get("price")

        # Extract image URL (check multiple possible keys)
        image_url = (
            item_dict.get("image_url")
            or item_dict.get("image")
            or item_dict.get("image_alt")
        )
        if image_url:
            image_url = image_url.strip()
            if not image_url:
                image_url = None

        # Extract other fields
        category = item_dict.get("category")
        if category:
            category = category.strip() or None
        sub_category = item_dict.get("sub_category")
        if sub_category:
            sub_category = sub_category.strip() or None
        color_primary = item_dict.get("color_primary") or item_dict.get("color")
        if color_primary:
            color_primary = color_primary.strip() or None
        color_secondary = item_dict.get("color_secondary")
        if color_secondary:
            color_secondary = color_secondary.strip() or None
        size = item_dict.get("size")
        if size:
            size = size.strip() or None

        # Deduplication check: look for existing item with same user_id, name, and brand
        # This prevents inserting exact duplicates from the same email
        # We use case-insensitive comparison for name and brand to catch variations
        query = db.query(ClothingItem).filter(
            ClothingItem.user_id == user_id,
        )
        
        # Case-insensitive name match
        query = query.filter(
            func.lower(ClothingItem.name) == name.lower()
        )
        
        # Brand match (both None or both equal, case-insensitive)
        if brand:
            query = query.filter(
                func.lower(ClothingItem.brand) == brand.lower()
            )
        else:
            query = query.filter(
                or_(ClothingItem.brand.is_(None), ClothingItem.brand == "")
            )
        
        existing_item = query.first()

        # If we found an existing item, skip creating a duplicate
        if existing_item:
            continue

        # Create new item
        clothing_item = ClothingItem(
            user_id=user_id,
            name=name,
            brand=brand,
            category=category,
            sub_category=sub_category,
            color_primary=color_primary,
            color_secondary=color_secondary,
            size=size,
        )
        db.add(clothing_item)
        db.flush()  # Get the ID without committing yet

        # Create ItemImage if we have an image URL
        if image_url:
            item_image = ItemImage(
                clothing_item_id=clothing_item.id,
                image_url=image_url,
                type="email",  # Mark as coming from email
                is_primary=True,
            )
            db.add(item_image)

        created_items.append(clothing_item)

    # Commit all new items at once
    if created_items:
        db.commit()
        # Refresh items to ensure they're fully loaded
        for item in created_items:
            db.refresh(item)

    return created_items

