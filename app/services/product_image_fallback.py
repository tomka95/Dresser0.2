"""Fallback product image generation using Google Gemini when no image is found in emails."""
# STATUS: implements fallback packshot generation for email-extracted items without images.

import asyncio
import base64
import logging
import re
from functools import partial
from typing import Optional
from uuid import uuid4

from app.platform.ai_provider import get_ai_provider
from app.utils.supabase_storage import SupabaseStorageClient

logger = logging.getLogger(__name__)


def _sanitize_filename(name: str) -> str:
    """Sanitize a string for use in a filename/path.
    
    Removes or replaces characters that are not safe for file paths.
    """
    # Replace spaces and special chars with underscores
    sanitized = re.sub(r'[^\w\s-]', '', name)
    # Replace spaces and multiple underscores with single underscore
    sanitized = re.sub(r'[\s_]+', '_', sanitized)
    # Remove leading/trailing underscores
    sanitized = sanitized.strip('_')
    # Limit length to avoid path issues
    if len(sanitized) > 100:
        sanitized = sanitized[:100]
    return sanitized or "item"


async def generate_product_packshot(shop_name: str, item_name: str) -> str:
    """
    Generate a product packshot image using Google Gemini and upload to Supabase.
    
    Creates a realistic e-commerce product photo on a plain white background
    matching the shop and item name. The image is saved to Supabase storage
    and a public URL is returned.
    
    Args:
        shop_name: Name of the shop/store (e.g., "Zara", "Lululemon")
        item_name: Name/description of the item (e.g., "Blue T-Shirt", "Flow Y Bra")
        
    Returns:
        Public URL string of the uploaded image
        
    Raises:
        ValueError: If image generation or upload fails
        asyncio.TimeoutError: If the operation exceeds 30 seconds
    """
    logger.info(f"Fallback packshot generation started for {shop_name} - {item_name}")
    
    try:
        # Build prompt for Gemini
        prompt = f"""Generate a realistic e-commerce product photo on a plain white background.

Product details:
- Shop/Store: {shop_name}
- Item: {item_name}

Requirements:
- Create a realistic product photo that matches the actual item as closely as possible
- Plain white (#FFFFFF) background, no gradients or patterns
- Product centered in the frame
- No people, no mannequin, no model, no human body parts
- No text overlays, no watermarks, no logos added unless they exist on the real product
- Be faithful to the brand and product name; do NOT invent unrelated designs
- Use professional e-commerce product photography style with natural shadows and lighting
- Show the product clearly and accurately based on the name

Output ONLY an image. No text, no explanation."""

        # Get AI provider and generate image
        ai = get_ai_provider()
        
        # Use asyncio.wait_for for timeout
        loop = asyncio.get_running_loop()
        resp = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                partial(
                    ai._client.models.generate_content,
                    model="gemini-2.5-flash-image",
                    contents=[{"text": prompt}]
                )
            ),
            timeout=30.0
        )
        
        # Extract image bytes from response
        image_bytes: Optional[bytes] = None
        
        if hasattr(resp, 'candidates') and resp.candidates:
            candidate = resp.candidates[0]
            if (
                hasattr(candidate, 'content')
                and candidate.content is not None
                and hasattr(candidate.content, 'parts')
                and candidate.content.parts is not None
            ):
                for part in candidate.content.parts:
                    if hasattr(part, 'inline_data') and hasattr(part.inline_data, 'data'):
                        data = part.inline_data.data
                        if data is not None:
                            if isinstance(data, bytes):
                                image_bytes = data
                                logger.debug(f"Extracted image bytes (length: {len(image_bytes)})")
                                break
                            elif isinstance(data, str):
                                try:
                                    image_bytes = base64.b64decode(data)
                                    logger.debug(f"Decoded base64 image bytes (length: {len(image_bytes)})")
                                    break
                                except (base64.binascii.Error, ValueError) as e:
                                    logger.warning(f"Failed to base64-decode image data: {e}")
        
        if not image_bytes:
            raise ValueError("Could not extract image bytes from Gemini response")
        
        # Sanitize shop and item names for path
        shop_sanitized = _sanitize_filename(shop_name) if shop_name else "unknown_shop"
        item_sanitized = _sanitize_filename(item_name) if item_name else "unknown_item"
        
        # Generate unique filename
        unique_id = uuid4().hex[:8]  # Short UUID for filename
        filename = f"{item_sanitized}-{unique_id}.png"
        
        # Build storage path: generated/{shop_name_sanitized}/{item_name_sanitized}-{uuid4()}.png
        folder = f"generated/{shop_sanitized}"
        
        # Upload to Supabase storage
        storage_client = SupabaseStorageClient.from_env()
        public_url = storage_client.upload_bytes(
            image_bytes=image_bytes,
            folder=folder,
            content_type="image/png",
            suffix=".png",
        )
        
        logger.info(f"Fallback packshot saved to Supabase: {public_url}")
        return public_url
        
    except asyncio.TimeoutError:
        logger.error(
            f"Timeout generating packshot for {shop_name} - {item_name} (exceeded 30s)",
            exc_info=True
        )
        raise
    except Exception as e:
        logger.error(
            f"Error generating packshot for {shop_name} - {item_name}: {e}",
            exc_info=True
        )
        raise
