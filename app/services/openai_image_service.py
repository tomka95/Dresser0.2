import os
import logging
from typing import Optional
from uuid import UUID
import httpx
from openai import AsyncOpenAI

from app.utils.supabase_storage import SupabaseStorageClient

logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def generate_white_bg_product_image_from_text(
    brand: str,
    product_name: str,
    user_id: UUID | str,
) -> Optional[str]:
    """
    Uses OpenAI's image generation to produce a single e-commerce style
    white-background product photo for the given brand + product name.
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
- Avoid text, logos, or watermarks on the image that are not part of the real product.

If some details are unclear from the name, make the safest generic choice that would
plausibly match the real product and avoid creative changes.
""".strip()

        # Call OpenAI Images API (DALL-E)
        logger.info(f"Generating product image for {brand} {product_name}")
        response = await client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            n=1,
            size="1024x1024",
            quality="standard",
        )

        # Get the image URL from the response
        image_url = response.data[0].url
        if not image_url:
            logger.error("OpenAI returned no image URL")
            return None

        # Download the image
        async with httpx.AsyncClient() as http_client:
            image_response = await http_client.get(image_url)
            image_response.raise_for_status()
            image_bytes = image_response.content

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
