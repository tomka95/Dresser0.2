"""Clothing pipeline service for detecting items and generating product images."""
# STATUS: uses one-call Gemini image+metadata flow per detected item.

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.services.ai_provider import get_ai_provider
from app.utils.image_loader import ImageLoader

logger = logging.getLogger(__name__)

CLOTHING_LIST_PROMPT = """
From the input image, you are a fashion vision assistant.

Task:
- Detect ALL visible clothing items and accessories worn by the person
  in the photo.

Output format:
- Return a SINGLE LINE containing a comma-separated list of short,
  human-readable item names, in order from top to bottom.
- Example: "dark navy NY Yankees cap, striped button-up shirt,
  camel wool coat, medium-wash straight-leg jeans, black flats with bow"

Constraints:
- Include accessories like hats, belts, bags, scarves, jewelry, shoes.
- Do not include hair, skin, body parts, or background objects.
- Do not include sizes or brands here.
- Do NOT add any extra text before or after the list.
"""

BRAND_JSON_PROMPT = """
You are a fashion product identifier.

You will be given a single product-style clothing image on a white background.

TASK:
- Infer the most likely fashion brands or labels that sell an item like this.
- Use your knowledge plus approximate pattern matching to guess brands and store links.
- If you cannot identify an exact match, provide the closest plausible brands that typically sell this style.

OUTPUT:
Return ONLY valid JSON, with no explanation, using this exact schema:

{
  "description": "<short plain-English description of the item>",
  "brand_candidates": [
    {
      "brand": "<brand name or label>",
      "confidence": <number between 0 and 1>,
      "notes": "<very short reason for this guess>"
    }
  ],
  "purchase_links": [
    {
      "label": "<store or marketplace name>",
      "url": "<https URL to a likely or approximate product page>",
      "notes": "<short note, e.g. 'exact match' or 'similar style'>"
    }
  ]
}

Rules:
- The JSON must be syntactically valid.
- Do not include comments or extra keys.
- If you are unsure, include lower confidence scores rather than omitting entries.
"""

ITEM_IMAGE_AND_METADATA_PROMPT = """
You are a fashion vision assistant. You are given an outfit photo.

CRITICAL: You MUST return TWO outputs in this single response:
(1) IMAGE: Generate a studio-quality ecommerce product photo of ONLY the {item_name}
    - Isolate ONLY the {item_name} from the outfit photo
    - Show it centered on a pure white (#FFFFFF) background
    - No person, mannequin, shadows, or text overlays
    - Professional product photography style
    - High resolution, well-lit, clean presentation

(2) TEXT: Output ONLY valid JSON (no markdown, no commentary) with this exact schema:

{{
  "name": "<descriptive product name: include primary color + brand if confident + item type. Example: 'Red Nike T-Shirt'>",
  "item_type": "<t-shirt|jeans|blazer|sneakers|dress|...>",
  "category": "<top|bottom|outerwear|shoes|accessory|...>",
  "brand": "<string or null>",
  "colors": [{{"name": "<color>", "score": 0.0-1.0, "hex": null}}],
  "materials": [{{"name": "<material>", "score": 0.0-1.0}}],
  "pattern": "<string or null>",
  "attributes": ["<short attribute>", "..."],
  "tags": [{{"text": "<tag>", "score": 0.0-1.0}}]
}}

FAILURE CONTRACT:
If you cannot generate the image for any reason, return ONLY this JSON in the TEXT part:
{{"error":"no_image_generated","reason":"<short reason>"}}

Rules:
- JSON must be syntactically valid
- Use null when unknown
- Keep "name" specific; avoid generic single-word names unless absolutely no info is available
- Do not invent brand unless visible or very confident
- BOTH IMAGE and TEXT are required unless you explicitly return the error JSON above
"""


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


async def detect_clothing_items(image_path: str) -> List[str]:
    """Call Vision to detect clothing items and return a list of item names."""
    image_data = await ImageLoader.load(image_path)
    ai = get_ai_provider()
    
    items = await ai.detect_clothing_items_from_image(image_data)
    return items


async def generate_item_image_with_responses(
    item_name: str,
    outfit_image_path: str,
    output_dir: str,
) -> Tuple[str, Dict[str, Any]]:
    """
    Generate a new product-style image of ONLY the given item from the original outfit photo.

    - Loads the outfit image.
    - Uses AI provider to generate a white-background product image.
    - Saves the result as PNG in output_dir and returns the file path.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Load the original outfit image as bytes + format
    image_data = await ImageLoader.load(outfit_image_path)
    
    # Get AI provider and generate product image + metadata in a single call
    ai = get_ai_provider()
    image_bytes, metadata = await ai.generate_product_image_and_metadata_from_outfit(
        item_name=item_name,
        outfit_image=image_data,
        json_prompt=ITEM_IMAGE_AND_METADATA_PROMPT.format(item_name=item_name),
    )

    # Handle case where image generation failed completely
    if image_bytes is None:
        raise ValueError(f"Image generation failed for item '{item_name}'")

    # Prefer descriptive name from metadata for filename when available
    metadata_name = metadata.get("name") if isinstance(metadata, dict) else None
    base_name = metadata_name or item_name

    # Save image to disk
    safe_name = sanitize_filename(base_name)
    final_path = Path(output_dir) / f"{safe_name}.png"

    with open(final_path, "wb") as f:
        f.write(image_bytes)

    return str(final_path), metadata


async def process_outfit_image(
    outfit_image_path: str,
    images_output_dir: str,
    json_summary_path: str,
) -> List[ItemResult]:
    """
    Full pipeline:
    - Detect clothing items.
    - For each item, asynchronously generate a product image and metadata.
    - Save JSON summary to `json_summary_path`.
    - Return list of ItemResult.
    """
    os.makedirs(images_output_dir, exist_ok=True)

    detected_items = await detect_clothing_items(outfit_image_path)

    # Generate item images + metadata using AI provider, with the original photo as input
    # Wrap each task to handle individual failures gracefully
    async def generate_with_error_handling(item: str) -> Tuple[Optional[str], Dict[str, Any]]:
        try:
            return await generate_item_image_with_responses(
                item_name=item,
                outfit_image_path=outfit_image_path,
                output_dir=images_output_dir,
            )
        except Exception as e:
            logger.error(f"Failed to generate image for item '{item}': {e}")
            return None, {"error": str(e), "item_name": item}
    
    image_tasks = [generate_with_error_handling(item) for item in detected_items]
    item_results: List[Tuple[Optional[str], Dict[str, Any]]] = await asyncio.gather(*image_tasks)

    results: List[ItemResult] = []
    for original_item_name, (img_path, meta) in zip(detected_items, item_results):
        # Skip items that failed to generate (None image path)
        if img_path is None:
            logger.warning(f"Skipping item '{original_item_name}' due to generation failure")
            continue
        
        item_display_name = (
            meta.get("name") if isinstance(meta, dict) and meta.get("name") else original_item_name
        )
        results.append(
            ItemResult(
                name=item_display_name,
                image_path=img_path,
                metadata=meta,
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

