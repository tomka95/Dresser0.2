from uuid import UUID
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models import ClothingItem, ItemImage, Tag
from app.utils.supabase_storage import SupabaseStorageClient


def save_outfit_results_to_db(
    db: Session,
    user_id: UUID,
    results: List[Any],  # List[ItemResult] from clothing_pipeline
    storage_client: SupabaseStorageClient,
) -> List[Dict[str, Any]]:
    """
    Takes pipeline results and persists them:
    - ClothingItem rows
    - ItemImage rows (with Supabase URLs)
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
            image_url = storage_client.upload_file(
                local_path=image_path,
                folder=str(user_id),
                content_type="image/png",  # adjust if JPEG
            )

            image = ItemImage(
                clothing_item_id=item.id,
                image_url=image_url,
                type="product",  # you can standardize this
                is_primary=True,
            )
            db.add(image)

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
