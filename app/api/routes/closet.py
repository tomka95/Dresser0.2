"""FastAPI router for Closet API endpoints."""

import logging
import time
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.models import User, ClothingItem, ItemImage
from app.services.closet_service import list_closet_items, create_closet_item

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
    Note: category is required in contract but DB allows null - we'll return null if not set.
    """
    
    id: str
    userId: str
    name: str
    category: str  # Contract requires enum value (default to "other" if DB has null)
    brand: Optional[str] = None
    color: Optional[str] = None
    imageUrl: Optional[str] = None
    createdAt: str
    updatedAt: str
    
    class Config:
        # Ensure camelCase field names in JSON output
        populate_by_name = True


def _get_image_url(item: ClothingItem) -> Optional[str]:
    """Get image URL for item, preferring clothing_items.image_url, then primary ItemImage.
    
    Optimized: Uses eagerly-loaded images relationship (no DB query).
    Assumes item.images is already loaded via selectinload in service layer.
    
    Args:
        item: ClothingItem instance with images relationship loaded
        
    Returns:
        Image URL string or None
    """
    # Prefer direct image_url field on ClothingItem
    if item.image_url:
        return item.image_url
    
    # Fallback to primary ItemImage (from eagerly-loaded relationship)
    # Find primary image in already-loaded images list (no DB query)
    primary_image = next(
        (img for img in item.images if img.is_primary),
        None
    )
    
    return primary_image.image_url if primary_image else None


def _map_clothing_item_to_out(item: ClothingItem) -> ClosetItemOut:
    """Map SQLAlchemy ClothingItem to ClosetItemOut contract format.
    
    Args:
        item: ClothingItem SQLAlchemy model with images relationship loaded
        
    Returns:
        ClosetItemOut Pydantic model with camelCase fields
    """
    # Get color: prefer color_primary, fallback to color_secondary
    color = item.color_primary or item.color_secondary or None
    
    # Get image URL using helper (no DB query - uses eagerly-loaded relationship)
    image_url = _get_image_url(item)
    
    # Handle category: contract requires enum value, but DB allows null
    # Use "other" as default if category is not set (matches contract requirement)
    category_value = item.category if item.category else "other"
    
    return ClosetItemOut(
        id=str(item.id),
        userId=str(item.user_id),
        name=item.name,
        category=category_value,
        brand=item.brand,
        color=color,
        imageUrl=image_url,
        createdAt=item.created_at.isoformat() if item.created_at else "",
        updatedAt=item.updated_at.isoformat() if item.updated_at else "",
    )


@router.get("", response_model=List[ClosetItemOut])
async def list_closet_items_endpoint(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[ClosetItemOut]:
    """List all clothing items for the authenticated user.
    
    Returns:
        List of ClosetItemOut objects matching the @tailor/contracts ClosetItem type
    """
    request_start = time.time()
    
    # DB query timing
    query_start = time.time()
    items = list_closet_items(db, current_user.id)
    query_time = (time.time() - query_start) * 1000  # Convert to milliseconds
    
    # Mapping/serialization timing
    mapping_start = time.time()
    result = [_map_clothing_item_to_out(item) for item in items]
    mapping_time = (time.time() - mapping_start) * 1000  # Convert to milliseconds
    
    total_time = (time.time() - request_start) * 1000  # Convert to milliseconds
    
    logger.info(
        f"[CLOSET_PERF] GET /closet - total={total_time:.2f}ms, "
        f"db_query={query_time:.2f}ms, mapping={mapping_time:.2f}ms, "
        f"items_count={len(items)}"
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

