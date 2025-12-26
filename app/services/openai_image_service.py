import asyncio
import logging
from functools import partial
from typing import Optional
from uuid import UUID

from app.services.ai_provider import get_ai_provider
from app.utils.supabase_storage import SupabaseStorageClient

logger = logging.getLogger(__name__)


async def _generate_image_from_text_prompt(prompt: str) -> bytes:
    """
    Generate an image from a text prompt using Gemini.
    
    TODO: This is a temporary implementation using text generation.
    This should be replaced with a proper text-to-image API call once
    the exact Gemini image-generation API is decided and available.
    
    Args:
        prompt: Text description of the image to generate
        
    Returns:
        Raw image bytes
        
    Raises:
        ValueError: If image bytes cannot be extracted from the response
    """
    ai = get_ai_provider()
    
    # TODO: Replace this with proper Gemini text-to-image API call
    # For now, using generate_content with text only as a placeholder
    # This will need to be updated when Gemini's image generation API is available
    loop = asyncio.get_running_loop()
    resp = await loop.run_in_executor(
        None,
        partial(
            ai._client.models.generate_content,
            model="gemini-1.5-flash",
            contents=[{"text": prompt}]
        )
    )
    
    # TODO: Extract image bytes from response
    # The exact structure depends on Gemini's response format for image generation
    # This is a placeholder that will need to be implemented based on
    # the actual response structure from Gemini's text-to-image API
    
    # Placeholder - this will need to be updated once we know the exact response format
    if hasattr(resp, 'candidates') and resp.candidates:
        candidate = resp.candidates[0]
        if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
            for part in candidate.content.parts:
                if hasattr(part, 'inline_data') and hasattr(part.inline_data, 'data'):
                    return part.inline_data.data
    
    # Fallback: raise an error if we can't extract the image
    raise ValueError("Could not extract image bytes from Gemini response")


async def generate_white_bg_product_image_from_text(
    brand: str,
    product_name: str,
    user_id: UUID | str,
) -> Optional[str]:
    """
    Uses AI provider to produce a single e-commerce style white-background
    product photo for the given brand + product name.
    Uploads the resulting image to Supabase storage and returns the public URL.
    
    Args:
        brand: Brand name (e.g., "Lululemon", "Zara")
        product_name: Product name/description (e.g., "Flow Y Bra Nulu Light Support")
        user_id: User ID for organizing uploads in Supabase storage
        
    Returns:
        Public URL of the uploaded image, or None if generation/upload fails
    """
    try:
        # Build explicit prompt to avoid creative redesign
        prompt = f"""
Generate a single high-resolution e-commerce product photo on a clean white background.

The product is: {brand} {product_name}.

Requirements:
- Match the style of official product photos on the brand's website
  (angle, proportions, logo placement) as closely as possible.
- Do NOT redesign or change the product. Do not change the colors, fabric type,
  neckline, straps, length, or other details implied by the product name.
- Do NOT add creative variations or new design elements.
- Show ONLY the product itself, centered, on a pure white (#FFFFFF) background.
- Do NOT put the product on a model or in a scene.
- Use high-quality product photography with natural shadows and professional lighting.
- Avoid text, logos, or watermarks on the image that are not part of the real product.

If some details are unclear from the name, make the safest generic choice that would
plausibly match the real product and avoid creative changes.
""".strip()

        # Generate image using AI provider
        logger.info(f"Generating product image for {brand} {product_name}")
        image_bytes = await _generate_image_from_text_prompt(prompt)

        if not image_bytes:
            logger.error("AI provider returned no image bytes")
            return None

        # Upload to Supabase storage
        storage_client = SupabaseStorageClient.from_env()
        folder = f"email_items/{user_id}"
        
        public_url = storage_client.upload_bytes(
            image_bytes=image_bytes,
            folder=folder,
            content_type="image/png",
            suffix=".png",
        )

        logger.info(f"Successfully generated and uploaded product image: {public_url}")
        return public_url

    except Exception as e:
        logger.error(
            f"Failed to generate product image for {brand} {product_name}: {e}",
            exc_info=True,
        )
        return None




