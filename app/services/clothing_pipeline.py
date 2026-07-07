"""Clothing pipeline service for detecting items and generating product images."""
# STATUS: uses batch image generation in a single Gemini call.

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from app.platform.ai_provider import get_ai_provider
from app.utils.image_loader import ImageLoader

logger = logging.getLogger(__name__)


@dataclass
class ItemResult:
    """Result for a single clothing item."""

    name: str  # e.g. "green plaid overshirt"
    image_path: str  # path to saved generated product image
    metadata: Dict[str, Any]  # JSON result from brand lookup


INVALID_FILENAME_CHARS = r'[<>:"/\\\\|?*\n\r\t]'


def sanitize_filename(item_name: str) -> str:
    """Sanitize item name for use as a Windows filename."""
    cleaned = item_name.strip().strip('"\'')
    # Remove invalid Windows filename characters
    cleaned = re.sub(INVALID_FILENAME_CHARS, "", cleaned)
    # Replace spaces with underscores
    cleaned = cleaned.replace(" ", "_")
    return cleaned or "item"


async def detect_clothing_items(image_path: str) -> Dict[str, Dict[str, Any]]:
    """Call Vision to detect clothing items and return a dict mapping item names to metadata."""
    image_data = await ImageLoader.load(image_path)
    ai = get_ai_provider()
    
    items_dict = await ai.detect_clothing_items_from_image(image_data)
    return items_dict


async def process_outfit_image(
    outfit_image_path: str,
    images_output_dir: str,
    json_summary_path: str,
) -> List[ItemResult]:
    """
    Full pipeline:
    - Detect clothing items with metadata.
    - Generate all product images in a single batch call.
    - Save JSON summary to `json_summary_path`.
    - Return list of ItemResult.
    """
    os.makedirs(images_output_dir, exist_ok=True)

    # Detect items and get metadata dict
    items_dict = await detect_clothing_items(outfit_image_path)
    item_names = list(items_dict.keys())
    
    if not item_names:
        logger.warning("No items detected in outfit image")
        return []
    
    # Load outfit image once for batch generation
    image_data = await ImageLoader.load(outfit_image_path)
    ai = get_ai_provider()
    
    # Generate all product images in a single batch call
    images_by_name = await ai.generate_product_images_from_outfit_batch(
        outfit_image=image_data,
        item_names=item_names
    )
    
    # Process each item: save images and build ItemResult objects
    results: List[ItemResult] = []
    for item_name in item_names:
        metadata = items_dict.get(item_name, {})
        image_bytes = images_by_name.get(item_name)
        
        # Skip items that failed to generate (missing image)
        if image_bytes is None:
            logger.warning(f"Skipping item '{item_name}' due to missing image in batch response")
            continue
        
        # Determine display name and filename base
        item_display_name = metadata.get("name") or item_name
        filename_base = metadata.get("name") or item_name
        
        # Save image to disk
        safe_name = sanitize_filename(filename_base)
        saved_path = Path(images_output_dir) / f"{safe_name}.png"
        
        with open(saved_path, "wb") as f:
            f.write(image_bytes)
        
        results.append(
            ItemResult(
                name=item_display_name,
                image_path=str(saved_path),
                metadata=metadata,
            )
        )

    # Save JSON summary: a list of objects with image name + metadata
    summary_payload = [
        {
            "item_name": r.name,
            "image_path": r.image_path,
            "metadata": r.metadata,
        }
        for r in results
    ]
    os.makedirs(os.path.dirname(json_summary_path), exist_ok=True)
    with open(json_summary_path, "w", encoding="utf-8") as f:
        json.dump(summary_payload, f, ensure_ascii=False, indent=2)

    return results

