import logging
from uuid import UUID
from typing import Any, Dict, List

import boto3
from botocore.exceptions import ClientError
from sqlalchemy.orm import Session

from app.models import ClothingItem, Tag
from app.utils.supabase_storage import SupabaseStorageClient

logger = logging.getLogger(__name__)


def save_outfit_results_to_db(
    db: Session,
    user_id: UUID,
    results: List[Any],  # List[ItemResult] from clothing_pipeline
    storage_client: SupabaseStorageClient,
) -> List[Dict[str, Any]]:
    """
    Takes pipeline results and persists them:
    - ClothingItem rows (with Supabase image URLs saved directly to image_url field)
    - Tag relations (if metadata['tags'] exists)

    Returns a list of simple dicts for API responses.
    """

    created_items: List[Dict[str, Any]] = []

    for r in results:
        # We assume ItemResult has: name, image_path, metadata: Dict[str, Any]
        metadata: Dict[str, Any] = getattr(r, "metadata", {}) or {}

        item = ClothingItem(
            user_id=user_id,
            name=getattr(r, "name", "Unknown item"),
            category=metadata.get("category"),
            sub_category=metadata.get("sub_category"),
            brand=metadata.get("brand"),
        )
        db.add(item)
        db.flush()  # assign item.id without full commit yet

        # Upload the product-style image to Supabase Storage
        image_path = getattr(r, "image_path", None)
        image_url = None
        if image_path:
            try:
                image_url = storage_client.upload_file(
                    local_path=image_path,
                    folder=str(user_id),
                    content_type="image/png",  # adjust if JPEG
                )

                # Save the image URL directly to the ClothingItem
                item.image_url = image_url
            except (boto3.exceptions.S3UploadFailedError, ClientError) as e:
                # Log warning but continue processing - item will be saved without image
                logger.warning(
                    f"Failed to upload image for item '{item.name}': {str(e)}"
                )
                image_url = None  # Ensure image_url is None if upload failed

        # Optional: tags
        tags = metadata.get("tags") or []
        for tag_name in tags:
            # simple get-or-create for Tag
            tag = db.query(Tag).filter(Tag.name == tag_name).first()
            if not tag:
                tag = Tag(name=tag_name)
                db.add(tag)
                db.flush()
            # relationship uses secondary="clothing_item_tags"
            item.tags.append(tag)

        created_items.append(
            {
                "id": str(item.id),
                "name": item.name,
                "brand": item.brand,
                "category": item.category,
                "sub_category": item.sub_category,
                "image_url": image_url,
            }
        )

    db.commit()
    return created_items
