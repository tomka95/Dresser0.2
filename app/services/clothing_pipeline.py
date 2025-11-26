"""Clothing pipeline service for detecting items and generating product images."""

import asyncio
import base64
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import httpx
from PIL import Image
from dotenv import load_dotenv
from openai import AsyncOpenAI

from app.utils.image_loader import ImageLoader

# Load environment variables from .env file
load_dotenv()

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

    b64_str = base64.b64encode(image_data.data).decode("utf-8")
    data_url = f"data:image/{image_data.format};base64,{b64_str}"

    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": CLOTHING_LIST_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    },
                ],
            }
        ],
    )

    text = resp.choices[0].message.content.strip()
    # Split by comma and normalize
    items = [part.strip() for part in text.split(",") if part.strip()]
    # Clean item names: strip quotes and whitespace
    items = [item.strip(' "\'') for item in items]
    return items


async def generate_item_image_with_responses(
    item_name: str,
    outfit_image_path: str,
    output_dir: str,
) -> str:
    """
    Using the Responses API, generate a new product-style image of ONLY
    the given item from the original outfit photo.

    - Sends the full outfit photo as an input_image.
    - Sends an input_text instruction referencing `item_name`.
    - Uses the built-in image_generation tool to produce a new image.
    - Saves the result as PNG in output_dir and returns the file path.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Load the original outfit image as bytes + format
    image_data = await ImageLoader.load(outfit_image_path)

    # Convert raw bytes to a base64 data URL string for JSON transport
    b64_str = base64.b64encode(image_data.data).decode("utf-8")

    # Derive a MIME type from the image format
    fmt = (image_data.format or "jpeg").lower()
    if fmt in ("jpg", "jpeg"):
        mime_type = "image/jpeg"
    else:
        mime_type = f"image/{fmt}"

    data_url = f"data:{mime_type};base64,{b64_str}"

    # Text instruction for this specific item
    instruction = f"""
You are an image editing assistant for a fashion e-commerce site.

You are given a full-body outfit photo of a person. Your task is to use
the built-in image_generation tool to generate a NEW studio-style product
image of ONLY this item from the photo:

Item: {item_name}

Requirements:
- Base the generated image on how this item actually appears in the photo:
  color, shade, pattern, material, logos, bows, seams, and other visible
  design details.
- Do NOT change or idealize the design. Preserve the real-world look as
  closely as possible.
- Remove the person and all other clothing items.
- Place the item on a clean white or very light neutral background.
- Use realistic studio lighting with soft, natural shadows.
- The item must be fully visible in frame (no edges cut off).
- Output a single, front-facing product-style image suitable for an
  online clothing catalog.
"""

    # Build Responses API input with both text and image
    response = await client.responses.create(
        model="gpt-4o",  # or "gpt-4.1" depending on what is configured
        tools=[{"type": "image_generation"}],
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": instruction},
                    {
                        "type": "input_image",
                        "image_url": data_url,
                    },
                ],
            }
        ],
    )

    # Extract the image_generation_call result (base64 image)
    image_base64 = None
    for output in response.output:
        if output.type == "image_generation_call":
            # In the Responses API, the generated image data is in .result
            image_base64 = output.result
            break

    if not image_base64:
        raise RuntimeError(
            f"No image_generation_call result returned for item: {item_name}"
        )

    # Save image to disk
    safe_name = sanitize_filename(item_name)
    final_path = Path(output_dir) / f"{safe_name}.png"

    with open(final_path, "wb") as f:
        f.write(base64.b64decode(image_base64))

    return str(final_path)


async def get_brand_metadata_for_image(image_path: str) -> Dict[str, Any]:
    """Get brand/store metadata for a generated product image."""
    image_data = await ImageLoader.load(image_path)

    # Encode raw bytes to base64 STRING and build a data URL
    b64_str = base64.b64encode(image_data.data).decode("utf-8")
    data_url = f"data:image/{image_data.format};base64,{b64_str}"

    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": BRAND_JSON_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    },
                ],
            }
        ],
    )
    raw = resp.choices[0].message.content.strip()

    # Best-effort JSON parsing
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Attempt to extract JSON from markdown code blocks if present
        if "```json" in raw:
            start = raw.find("```json") + 7
            end = raw.find("```", start)
            if end > start:
                raw = raw[start:end].strip()
                data = json.loads(raw)
            else:
                raise
        elif "```" in raw:
            start = raw.find("```") + 3
            end = raw.find("```", start)
            if end > start:
                raw = raw[start:end].strip()
                data = json.loads(raw)
            else:
                raise
        else:
            raise

    return data


async def process_outfit_image(
    outfit_image_path: str,
    images_output_dir: str,
    json_summary_path: str,
) -> List[ItemResult]:
    """
    Full pipeline:
    - Detect clothing items.
    - For each item, asynchronously generate a product image.
    - For each generated image, get brand/store metadata.
    - Save JSON summary to `json_summary_path`.
    - Return list of ItemResult.
    """
    os.makedirs(images_output_dir, exist_ok=True)

    detected_items = await detect_clothing_items(outfit_image_path)

    # Generate item images using Responses API, with the original photo as input
    image_tasks = [
        generate_item_image_with_responses(
            item_name=item,
            outfit_image_path=outfit_image_path,
            output_dir=images_output_dir,
        )
        for item in detected_items
    ]
    image_paths = await asyncio.gather(*image_tasks)

    # For metadata, also run in parallel
    metadata_tasks = [
        get_brand_metadata_for_image(image_path=img_path) for img_path in image_paths
    ]
    metadatas = await asyncio.gather(*metadata_tasks)

    results: List[ItemResult] = []
    for item, img_path, meta in zip(detected_items, image_paths, metadatas):
        results.append(
            ItemResult(
                name=item,
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

