"""FastAPI router for Closet API endpoints."""

import logging
import time
from typing import ClassVar, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.models import User, ClothingItem, ItemImage
from app.services.closet_service import (
    list_closet_items,
    create_closet_item,
    get_closet_item_by_id,
    update_closet_item,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/closet",
    tags=["closet"],
)

# Category enum matching @tailor/contracts
CATEGORY_ENUM = ['top', 'bottom', 'dress', 'outerwear', 'shoes', 'accessories', 'other']


class ClosetItemCreateIn(BaseModel):
    """Input schema for creating a closet item."""
    
    name: str = Field(..., min_length=1, description="Item name (required)")
    category: Optional[str] = Field(None, description="Item category")
    brand: Optional[str] = Field(None, description="Item brand")
    color: Optional[str] = Field(None, description="Item color")
    imageUrl: Optional[str] = Field(None, description="Image URL")
    
    @field_validator('category')
    @classmethod
    def validate_category(cls, v: Optional[str]) -> Optional[str]:
        """Validate category matches contract enum."""
        if v is not None and v not in CATEGORY_ENUM:
            raise ValueError(f"Category must be one of: {', '.join(CATEGORY_ENUM)}")
        return v


class ClosetItemOut(BaseModel):
    """Output schema matching ClosetItem contract from @tailor/contracts.

    All fields are camelCase to match the frontend contract exactly.
    Note: category is required in contract but DB allows null - we'll return "other" if not set.
    """

    id: str
    userId: str
    name: str
    category: str  # Contract requires enum value (default to "other" if DB has null)
    brand: Optional[str] = None
    color: Optional[str] = None
    size: Optional[str] = None
    quantity: int = 1
    unitPrice: Optional[float] = None
    currency: Optional[str] = None
    orderDate: Optional[str] = None
    isReturn: bool = False
    merchant: Optional[str] = None
    imageUrl: Optional[str] = None
    createdAt: str
    updatedAt: str

    class Config:
        # Ensure camelCase field names in JSON output
        populate_by_name = True


def _get_image_url(item: ClothingItem) -> Optional[str]:
    """Get image URL for item, preferring clothing_items.image_url, then primary ItemImage.
    
    Optimized: Uses eagerly-loaded images relationship if available (no DB query).
    Falls back to lazy loading if images relationship not yet loaded.
    
    Args:
        item: ClothingItem instance (images relationship may or may not be loaded)
        
    Returns:
        Image URL string or None
    """
    # Prefer direct image_url field on ClothingItem
    if item.image_url:
        return item.image_url
    
    # Fallback to primary ItemImage from images relationship
    # Accessing item.images will trigger lazy load if not already loaded
    if hasattr(item, 'images') and item.images:
        primary_image = next(
            (img for img in item.images if img.is_primary),
            None
        )
        if primary_image:
            return primary_image.image_url
    
    return None


def _map_clothing_item_to_out(
    item: ClothingItem,
    include_tags: bool = True,  # Ignored for backward compatibility, no longer used
) -> ClosetItemOut:
    """Map SQLAlchemy ClothingItem to ClosetItemOut contract format.

    merchant is read directly from the persisted clothing_items.merchant column
    (Wave 2a); there is no longer a display-time join against ingest_candidates.
    """
    color = item.color_primary or item.color_secondary or None
    image_url = _get_image_url(item)
    category_value = item.category if item.category else "other"

    unit_price = float(item.unit_price) if item.unit_price is not None else None
    order_date = item.order_date.isoformat() if item.order_date else None

    return ClosetItemOut(
        id=str(item.id),
        userId=str(item.user_id),
        name=item.name,
        category=category_value,
        brand=item.brand,
        color=color,
        size=item.size,
        quantity=item.quantity if item.quantity is not None else 1,
        unitPrice=unit_price,
        currency=item.currency,
        orderDate=order_date,
        isReturn=bool(item.is_return),
        merchant=item.merchant,
        imageUrl=image_url,
        createdAt=item.created_at.isoformat() if item.created_at else "",
        updatedAt=item.updated_at.isoformat() if item.updated_at else "",
    )


@router.get("", response_model=List[ClosetItemOut])
async def list_closet_items_endpoint(
    include_tags: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[ClosetItemOut]:
    """List all clothing items for the authenticated user.
    
    Args:
        include_tags: If True, include tags in response (default: False for performance)
        current_user: Authenticated user from JWT
        db: Database session
        
    Returns:
        List of ClosetItemOut objects matching the @tailor/contracts ClosetItem type
    """
    request_start = time.time()
    
    # DB query timing
    query_start = time.time()
    items = list_closet_items(db, current_user.id, include_tags=include_tags)
    query_time = (time.time() - query_start) * 1000  # Convert to milliseconds

    # Mapping/serialization timing. merchant now lives on clothing_items (Wave 2a) —
    # no per-request join against ingest_candidates.
    mapping_start = time.time()
    result = [
        _map_clothing_item_to_out(item, include_tags=include_tags)
        for item in items
    ]
    mapping_time = (time.time() - mapping_start) * 1000  # Convert to milliseconds
    
    total_time = (time.time() - request_start) * 1000  # Convert to milliseconds
    
    logger.info(
        f"[CLOSET_PERF] GET /closet - total={total_time:.2f}ms, "
        f"db_query={query_time:.2f}ms, mapping={mapping_time:.2f}ms, "
        f"items_count={len(items)}, include_tags={include_tags}"
    )
    
    return result


@router.post("", response_model=ClosetItemOut, status_code=201)
async def create_closet_item_endpoint(
    input_data: ClosetItemCreateIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ClosetItemOut:
    """Create a new clothing item for the authenticated user.
    
    Args:
        input_data: ClosetItemCreateIn with item details
        current_user: Authenticated user from JWT
        db: Database session
        
    Returns:
        ClosetItemOut object matching the @tailor/contracts ClosetItem type
        
    Raises:
        HTTPException: If validation fails
    """
    try:
        # Validate name is non-empty (Pydantic handles this, but double-check)
        if not input_data.name or not input_data.name.strip():
            raise HTTPException(status_code=400, detail="Item name is required and cannot be empty")
        
        # Create item via service layer
        item = create_closet_item(
            db=db,
            user_id=current_user.id,
            name=input_data.name.strip(),
            category=input_data.category,
            brand=input_data.brand,
            color=input_data.color,
            image_url=input_data.imageUrl,  # Map camelCase input to snake_case parameter
        )
        
        # Map to contract format
        # For POST, we need to ensure images are loaded if item.image_url is not set
        # Since this is a single item, trigger lazy load if needed (usually image_url is set)
        if not item.image_url:
            # Load images relationship for this single item (lazy load - one query)
            _ = item.images
        return _map_clothing_item_to_out(item)
        
    except ValueError as e:
        # Pydantic validation errors (e.g., invalid category)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create closet item for user {current_user.id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to create closet item")


class ClosetItemUpdateIn(BaseModel):
    """Input schema for updating a closet item (partial updates)."""

    name: Optional[str] = Field(None, min_length=1, description="Item name")
    category: Optional[str] = Field(None, description="Item category")
    brand: Optional[str] = Field(None, description="Item brand")
    color: Optional[str] = Field(None, description="Item color")
    size: Optional[str] = Field(None, description="Item size")
    unitPrice: Optional[float] = Field(None, description="Unit price")
    currency: Optional[str] = Field(None, description="3-char ISO-4217 currency code")
    imageUrl: Optional[str] = Field(None, description="Image URL")

    @field_validator('category')
    @classmethod
    def validate_category(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in CATEGORY_ENUM:
            raise ValueError(f"Category must be one of: {', '.join(CATEGORY_ENUM)}")
        return v


@router.get("/{item_id}", response_model=ClosetItemOut)
async def get_closet_item_endpoint(
    item_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ClosetItemOut:
    """Get a single clothing item by ID for the authenticated user.
    
    Args:
        item_id: UUID of the clothing item
        current_user: Authenticated user from JWT
        db: Database session
        
    Returns:
        ClosetItemOut object matching the @tailor/contracts ClosetItem type,
        including tags array
        
    Raises:
        HTTPException: 404 if item not found or doesn't belong to user
    """
    item = get_closet_item_by_id(db, current_user.id, item_id)

    if not item:
        raise HTTPException(
            status_code=404,
            detail=f"Clothing item {item_id} not found or access denied"
        )

    return _map_clothing_item_to_out(item)


@router.patch("/{item_id}", response_model=ClosetItemOut)
async def update_closet_item_endpoint(
    item_id: UUID,
    input_data: ClosetItemUpdateIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ClosetItemOut:
    """Update a clothing item with partial fields and optionally replace tags.
    
    All updates (fields + tags) are performed atomically in a single transaction.
    Only updates fields that are provided (not None).
    If tags are provided, they replace all existing tags atomically.
    
    Args:
        item_id: UUID of the clothing item
        input_data: ClosetItemUpdateIn with fields to update
        current_user: Authenticated user from JWT
        db: Database session
        
    Returns:
        Updated ClosetItemOut object matching the @tailor/contracts ClosetItem type
        
    Raises:
        HTTPException: 404 if item not found or doesn't belong to user
        HTTPException: 400 if validation fails (e.g., empty name)
        HTTPException: 422 if Pydantic validation fails
    """
    try:
        # Prepare field updates
        update_kwargs = {}
        if input_data.name is not None:
            update_kwargs['name'] = input_data.name
        if input_data.category is not None:
            update_kwargs['category'] = input_data.category
        if input_data.brand is not None:
            update_kwargs['brand'] = input_data.brand
        if input_data.color is not None:
            update_kwargs['color'] = input_data.color
        if input_data.size is not None:
            update_kwargs['size'] = input_data.size
        if input_data.unitPrice is not None:
            update_kwargs['unit_price'] = input_data.unitPrice
        if input_data.currency is not None:
            update_kwargs['currency'] = input_data.currency
        if input_data.imageUrl is not None:
            update_kwargs['image_url'] = input_data.imageUrl
        
        # Perform all updates atomically in one transaction
        # First, verify item exists and user owns it (without eager loading for performance)
        item = (
            db.query(ClothingItem)
            .filter(ClothingItem.id == item_id)
            .filter(ClothingItem.user_id == current_user.id)
            .first()
        )
        if not item:
            raise HTTPException(
                status_code=404,
                detail=f"Clothing item {item_id} not found or access denied"
            )
        
        # Update item fields directly (without committing)
        if update_kwargs:
            # Validate name if provided
            if 'name' in update_kwargs:
                name = update_kwargs['name'].strip()
                if not name:
                    raise ValueError("Item name cannot be empty")
                item.name = name
            
            # Update other fields
            if 'category' in update_kwargs:
                item.category = update_kwargs['category']
            if 'brand' in update_kwargs:
                item.brand = update_kwargs['brand']
            if 'color' in update_kwargs:
                item.color_primary = update_kwargs['color']
            if 'size' in update_kwargs:
                item.size = update_kwargs['size']
            if 'unit_price' in update_kwargs:
                item.unit_price = update_kwargs['unit_price']
            if 'currency' in update_kwargs:
                item.currency = update_kwargs['currency']
            if 'image_url' in update_kwargs:
                item.image_url = update_kwargs['image_url']
        
        # Commit all changes atomically
        db.commit()
        db.refresh(item)
        
        # Eagerly load relationships for response
        _ = item.images  # Trigger lazy load if not already loaded

        return _map_clothing_item_to_out(item)
        
    except ValueError as e:
        # Validation errors (e.g., empty name)
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        # Re-raise HTTP exceptions (404, etc.)
        raise
    except Exception as e:
        # Rollback on error
        db.rollback()
        logger.error(
            f"Failed to update closet item {item_id} for user {current_user.id}: {e}"
        )
        raise HTTPException(status_code=500, detail="Failed to update closet item")

