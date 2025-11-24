"""Clothing pipeline service for detecting items and generating product images."""

import asyncio
import base64
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from openai import AsyncOpenAI

from app.utils.image_loader import ImageLoader

# Load environment variables from .env file
load_dotenv()

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

CLOTHING_LIST_PROMPT = """
You are a fashion vision parser.

You will be given a single photo of a person wearing clothes.

TASK:
1. Identify ALL distinct visible clothing items and accessories worn by the person (outerwear, tops, bottoms, dresses, shoes, hats, bags, jewelry, belts, etc.).
2. Return them as a SINGLE LINE, comma-separated list, from outermost layer to innermost, left to right where reasonable.
3. Use short, concrete descriptions (e.g. "green plaid overshirt", "cream hoodie", "beige chinos", "white sneakers").
4. DO NOT include the person, body parts, background, or duplicate synonyms.

OUTPUT FORMAT:
- EXACTLY one line of plain text
- Items separated by commas
- No numbering, no bullets, no extra commentary.

Example of correct style:
"burgundy bomber jacket, striped knit sweater, light wash straight jeans, white sneakers"
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
    """Given a local image path, call OpenAI Vision and return a list of item names."""
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
    items = [part.strip() for part in text.split(",") if part.strip()]
    # Clean item names: strip quotes and whitespace
    items = [item.strip(' "\'') for item in items]
    return items


def build_item_image_prompt(item_name: str) -> str:
    return f"""
You are a product photographer for an online clothing store.

Your job is to create a photo that looks like a REAL, existing garment,
not a 3D render or illustration.

ITEM TO SHOW:
- A {item_name} taken from the outfit in the original photo.

STYLE & REALISM:
- It must look like a natural studio photograph of a physical garment.
- Avoid any "AI art" look, surreal lighting, neon glows, or exaggerated sharpness.
- Show subtle, realistic fabric texture and small, natural wrinkles.
- Preserve realistic stitching, seams, hems, pockets, buttons, zippers, and tags.
- If there is visible printed text or a logo on the original item, copy the visible
  text exactly and DO NOT invent new words or brands.

FRAMING & BACKGROUND:
- Show the entire garment clearly inside the frame (no cropping off edges).
- Use a clean, plain white or very light neutral background.
- Use simple, even studio lighting with soft shadows.
- No models, no body parts, no props, no environment.

FAITHFULNESS TO ORIGINAL:
- Match the true colors, pattern layout, and proportions of the original item
  as closely as possible.
- Do NOT idealize, stylize, or redesign the garment.
- Do NOT change fit, silhouette, or key details.

OUTPUT:
- A single front-facing, product-style photo of ONLY this {item_name},
  suitable for an e-commerce product listing and for visual search to
  find similar real-world products.
"""


async def generate_item_image(item_name: str, output_dir: str) -> str:
    """Generate a product-style image for a single item and save it to output_dir."""
    os.makedirs(output_dir, exist_ok=True)
    prompt = build_item_image_prompt(item_name)

    img_resp = await client.images.generate(
        model="dall-e-3",  # Note: Using dall-e-3 (user specified gpt-image-1)
        prompt=prompt,
        size="1024x1024",
        n=1,
        response_format="b64_json",
    )

    b64_data = img_resp.data[0].b64_json

    safe_name = sanitize_filename(item_name)
    file_path = Path(output_dir) / f"{safe_name}.png"

    with open(file_path, "wb") as f:
        f.write(base64.b64decode(b64_data))

    return str(file_path)


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
    items = await detect_clothing_items(outfit_image_path)

    # Generate all product images in parallel
    image_tasks = [
        generate_item_image(item_name=item, output_dir=images_output_dir)
        for item in items
    ]
    image_paths = await asyncio.gather(*image_tasks)

    # For metadata, also run in parallel
    metadata_tasks = [
        get_brand_metadata_for_image(image_path=img_path) for img_path in image_paths
    ]
    metadatas = await asyncio.gather(*metadata_tasks)

    results: List[ItemResult] = []
    for item_name, img_path, meta in zip(items, image_paths, metadatas):
        results.append(ItemResult(name=item_name, image_path=img_path, metadata=meta))

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

