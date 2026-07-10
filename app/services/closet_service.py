"""Service layer for closet/clothing items operations."""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, selectinload

from app.models import ClothingItem, IngestCandidate, IngestRun
from app.services.closet_canonicalize import (
    CanonFields,
    canonicalize_fields,
    load_user_facts,
)

logger = logging.getLogger(__name__)


def list_closet_items(
    db: Session,
    user_id: UUID,
    include_tags: bool = False,  # Ignored for backward compatibility, no longer used
) -> List[ClothingItem]:
    """List all clothing items for a user with images eagerly loaded.

    Uses selectinload to fetch all ItemImage relationships in a single query,
    avoiding N+1 queries when checking for primary images.

    Excludes archived_at rows — the same filter every other read path already
    applies (ranking/features, ranking/feed, stylist retrieval, todays_look). This
    was the one outlier: the closet grid was still listing archived/quarantined
    items (Photo-seam Phase 6b: quarantined non-clothing rows must not surface
    anywhere, including here).

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
        .filter(ClothingItem.user_id == user_id, ClothingItem.archived_at.is_(None))
        .options(selectinload(ClothingItem.images))  # Always load images
        .order_by(ClothingItem.created_at.desc())
        .all()
    )
    return items


def create_manual_candidate(
    db: Session,
    user_id: UUID,
    name: str,
    category: str | None = None,
    brand: str | None = None,
    color: str | None = None,
    image_url: str | None = None,
) -> Tuple[IngestRun, IngestCandidate]:
    """Stage a typed MANUAL add as an ingest candidate (Photo-seam Phase 4).

    A manual add no longer inserts a clothing_item directly — the confirm chokepoint
    is the ONLY birth path. This stages a source_type='manual' candidate inside its
    own 1-candidate ingest_run so the shared settle/status/strand-heal machinery
    covers it; the manual generation pass then produces the invariant-compliant card
    through the ONE shared seam (reference-conditioned when the user supplied an
    image, t2i from attributes otherwise), and auto-confirms on 'ready'.

    Canonicalization is the same chokepoint the confirm path uses: category inferred
    when blank, descriptive name, size defaulted from onboarding facts.sizes (missing
    size -> the shared needs-size rule at review, never blocked-forever).

    ``image_url`` (optional, already validated/stored by the route) is kept ONLY as
    the generation REFERENCE — it is never the display image (person_status stays
    fail-closed 'unknown' until the verified card stamps person_free).
    """
    canon = canonicalize_fields(
        CanonFields(name=name, category=category, brand=brand, color=color),
        load_user_facts(db, user_id),
        source_provenance="user_edited",
    )
    sync_id = uuid4()
    run = IngestRun(
        sync_id=sync_id, user_id=user_id, status="running", source_type="manual",
    )
    db.add(run)
    cand = IngestCandidate(
        user_id=user_id,
        sync_id=sync_id,
        # Random per-add key: a manual add is deliberate — never dedup-merged away.
        source_line_key=f"manual:{uuid4().hex}",
        message_id=None,
        source_message_ids=[],
        seen_count=1,
        name=canon.name,
        brand=canon.brand,
        category=canon.category,
        color=canon.color,
        size=canon.size,
        image_url=image_url,
        image_status="user_uploaded" if image_url else "pending",
        source_type="manual",
        pipeline_state="staged",
        person_status="unknown",  # fail-closed until the verified card lands
        status="pending",
        confidence_overall=1.0,   # the user typed it
    )
    db.add(cand)
    db.commit()
    db.refresh(run)
    db.refresh(cand)
    logger.info(
        "manual add staged user=%s sync=%s candidate=%s (ref_image=%s)",
        user_id, sync_id, cand.id, bool(image_url),
    )
    return run, cand


def get_closet_item_by_id(
    db: Session,
    user_id: UUID,
    item_id: UUID,
) -> Optional[ClothingItem]:
    """Get a single clothing item by ID for a user with images eagerly loaded.

    Uses selectinload to fetch images relationship in a single query,
    avoiding N+1 queries.

    Excludes archived_at rows — a quarantined (Photo-seam Phase 6b) or user-
    archived item must not be directly reachable by id either; this was the last
    read path missing the filter every other surface already applies.

    Args:
        db: Database session
        user_id: UUID of the user (for security check)
        item_id: UUID of the clothing item

    Returns:
        ClothingItem SQLAlchemy model with images relationship loaded,
        or None if not found, doesn't belong to user, or is archived
    """
    item = (
        db.query(ClothingItem)
        .filter(ClothingItem.id == item_id)
        .filter(ClothingItem.user_id == user_id)  # Security: ensure user owns the item
        .filter(ClothingItem.archived_at.is_(None))
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
        # User-chosen replacement image: deliberate display choice (see create above).
        item.person_status = "person_free"
    
    # updated_at is automatically updated by SQLAlchemy's onupdate
    
    if commit:
        db.commit()
        db.refresh(item)
    
    logger.info(f"Updated clothing item {item.id} for user {user_id}")
    
    return item

