"""AI provider abstraction layer for supporting multiple LLM providers (Gemini, OpenAI, etc.)."""
# STATUS: implements Gemini image+metadata generation with shared JSON extraction helper.

from __future__ import annotations

import asyncio
import base64
import json
import logging
from dataclasses import dataclass
from functools import partial
from typing import Any, Dict, List, Optional, Tuple

from google import genai
from google.genai import types

from app.core.config import settings


logger = logging.getLogger(__name__)


@dataclass
class DetectedItem:
    """Represents a detected clothing item."""
    name: str


def extract_json_metadata(response_text: str) -> Dict[str, Any]:
    """
    Extract a JSON object from a model text response.

    Handles both raw JSON and ```json fenced blocks. Returns an empty dict
    if parsing fails or the result is not a JSON object.
    """
    if not isinstance(response_text, str):
        return {}

    text = response_text.strip()

    # Try to unwrap markdown fences if present
    if "```" in text:
        # Prefer ```json fences when present
        if "```json" in text:
            start = text.find("```json") + len("```json")
        else:
            start = text.find("```") + len("```")

        end = text.find("```", start)
        if end != -1:
            text = text[start:end].strip()

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Failed to parse JSON metadata from model response: %s", exc)
        return {}


class AIProvider:
    """Abstraction layer for AI providers (Gemini, OpenAI, etc.)."""
    
    def __init__(self):
        """Initialize the AI provider based on configuration."""
        provider = settings.LLM_PROVIDER
        
        if provider == "gemini":
            self._provider = "gemini"
            # Pass API key explicitly from settings, or let it read from GOOGLE_API_KEY env var
            api_key = settings.GEMINI_API_KEY
            if api_key:
                self._client = genai.Client(api_key=api_key)
            else:
                # Fallback: let genai.Client() read from GOOGLE_API_KEY environment variable
                self._client = genai.Client()
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")
    
    async def detect_clothing_items_from_image(
        self,
        outfit_image,
        *,
        max_items: int = 10
    ) -> List[str]:
        """
        Detect clothing items from an outfit image.
        
        Args:
            outfit_image: Image object with `.data` (bytes) and `.format` (str or None)
            max_items: Maximum number of items to detect
            
        Returns:
            List of detected clothing item names
        """
        # Build prompt for Gemini
        prompt = f"""Look at this outfit photo and list up to {max_items} clothing items you can see.
Return only a comma-separated list of item names, nothing else.
Examples: "t-shirt, jeans, sneakers" or "dress, sandals"
"""
        
        # Determine MIME type from format or default to jpeg
        mime_type = "image/jpeg"
        if outfit_image.format:
            format_lower = outfit_image.format.lower()
            if format_lower in ["png", "jpg", "jpeg"]:
                mime_type = f"image/{format_lower if format_lower != 'jpg' else 'jpeg'}"
        
        # Prepare multimodal request parts
        parts = [
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": outfit_image.data
                }
            },
            {"text": prompt}
        ]
        
        # Run Gemini call in thread executor
        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(
            None,
            partial(
                self._client.models.generate_content,
                model="gemini-2.5-flash-image",
                contents=parts
            )
        )
        
        # Extract and parse response
        response_text = resp.text.strip()
        
        # Split on commas and normalize
        items = [
            item.strip().strip('"').strip("'")
            for item in response_text.split(",")
            if item.strip()
        ]
        
        return items[:max_items]
    
    async def get_brand_metadata_for_image(
        self,
        product_image,
        *,
        json_prompt: str
    ) -> Dict[str, Any]:
        """
        Extract brand metadata from a product image using a JSON prompt.
        
        Args:
            product_image: Image object with `.data` (bytes) and `.format` (str or None)
            json_prompt: Prompt instructing the model to return JSON metadata
            
        Returns:
            Dictionary containing extracted metadata, or empty dict if parsing fails
        """
        # Determine MIME type from format or default to jpeg
        mime_type = "image/jpeg"
        if product_image.format:
            format_lower = product_image.format.lower()
            if format_lower in ["png", "jpg", "jpeg"]:
                mime_type = f"image/{format_lower if format_lower != 'jpg' else 'jpeg'}"
        
        # Prepare multimodal request parts
        parts = [
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": product_image.data
                }
            },
            {"text": json_prompt}
        ]
        
        # Run Gemini call in thread executor
        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(
            None,
            partial(
                self._client.models.generate_content,
                model="gemini-2.5-flash-image",
                contents=parts
            )
        )
        
        # Extract response text and try to parse as JSON
        response_text = resp.text.strip()
        return extract_json_metadata(response_text)
    
    async def generate_product_image_from_outfit(
        self,
        *,
        item_name: str,
        outfit_image
    ) -> bytes:
        """
        Generate a white-background e-commerce style product image by isolating
        a specific item from an outfit photo.
        
        Args:
            item_name: Name of the clothing item to isolate (e.g., "t-shirt", "jeans")
            outfit_image: Image object with `.data` (bytes) and `.format` (str or None)
            
        Returns:
            Image bytes of the generated product image
        """
        # Build instructions for isolating the item
        prompt = f"""Look at this outfit photo and isolate ONLY the {item_name} from the image.
Create a white-background e-commerce style product image showing just this item.

Requirements:
- Show ONLY the {item_name}, centered on a pure white background
- Remove any other clothing items, models, or background elements
- Maintain the original style, color, and details of the {item_name}
- Use professional e-commerce product photo styling
"""
        
        # Determine MIME type from format or default to jpeg
        mime_type = "image/jpeg"
        if outfit_image.format:
            format_lower = outfit_image.format.lower()
            if format_lower in ["png", "jpg", "jpeg"]:
                mime_type = f"image/{format_lower if format_lower != 'jpg' else 'jpeg'}"
        
        # Prepare multimodal request parts
        parts = [
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": outfit_image.data
                }
            },
            {"text": prompt}
        ]
        
        # Run Gemini call in thread executor
        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(
            None,
            partial(
                self._client.models.generate_content,
                model="gemini-2.5-flash-image",
                contents=parts
            )
        )
        
        # TODO: Extract raw image bytes from the response
        # The exact structure depends on Gemini's response format for image generation
        # For now, this is a placeholder that will need to be implemented based on
        # the actual response structure from Gemini's image generation API
        # Expected structure might be something like:
        # resp.candidates[0].content.parts[0].inline_data.data
        # or similar, depending on the actual API response
        #TODO: Raise value error here doesnt point to the problem, FIX IT
        if hasattr(resp, 'candidates') and resp.candidates:
            candidate = resp.candidates[0]
            if hasattr(candidate, 'content') and candidate.content is not None and hasattr(candidate.content, 'parts') and candidate.content.parts is not None:
                for part in candidate.content.parts:
                    if hasattr(part, "inline_data") and hasattr(part.inline_data, "data"):
                        data = part.inline_data.data
                        # The SDK may return either bytes or base64-encoded string
                        if isinstance(data, bytes):
                            return data
                        if isinstance(data, str):
                            try:
                                return base64.b64decode(data)
                            except (base64.binascii.Error, ValueError):
                                logger.warning("Failed to base64-decode inline image data")
        
        # Fallback: raise an error if we can't extract the image
        raise ValueError("Could not extract image bytes from Gemini response")

    async def generate_product_image_and_metadata_from_outfit(
        self,
        *,
        item_name: str,
        outfit_image,
        json_prompt: str,
    ) -> Tuple[Optional[bytes], Dict[str, Any]]:
        """
        Single-call flow that generates a product image and JSON metadata.

        Uses the Gemini image model with multimodal output (TEXT + IMAGE).
        Returns (image_bytes, metadata_dict). image_bytes may be None if generation failed.
        """
        # Determine MIME type from format or default to jpeg
        mime_type = "image/jpeg"
        if getattr(outfit_image, "format", None):
            format_lower = outfit_image.format.lower()
            if format_lower in ["png", "jpg", "jpeg"]:
                mime_type = f"image/{format_lower if format_lower != 'jpg' else 'jpeg'}"

        # Build prompt with explicit IMAGE + TEXT requirement
        prompt = f"{json_prompt}\n\nCRITICAL: You must return BOTH an IMAGE part and a TEXT part (JSON only, no markdown) in this single response."

        # Build contents - use dict format for parts (matches working pattern)
        parts = [
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": outfit_image.data,
                }
            },
            {"text": prompt},
        ]

        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(
            None,
            partial(
                self._client.models.generate_content,
                model="gemini-2.5-flash-image",
                contents=parts,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"]
                ),
            ),
        )

        image_bytes: Optional[bytes] = None
        metadata: Dict[str, Any] = {}
        json_text: Optional[str] = None

        # Extract image and text from response
        if hasattr(resp, "candidates") and resp.candidates:
            candidate = resp.candidates[0]
            if (
                hasattr(candidate, "content")
                and candidate.content is not None
                and hasattr(candidate.content, "parts")
                and candidate.content.parts is not None
            ):
                parts = candidate.content.parts
                for part in parts:
                    # Image bytes via inline_data
                    if hasattr(part, "inline_data") and hasattr(part.inline_data, "data"):
                        data = part.inline_data.data
                        if data is not None:
                            if isinstance(data, bytes):
                                image_bytes = data
                                logger.debug(f"Found image bytes (bytes, length: {len(image_bytes)})")
                            elif isinstance(data, str):
                                try:
                                    image_bytes = base64.b64decode(data)
                                    logger.debug(f"Found image bytes (base64 string, decoded length: {len(image_bytes)})")
                                except (base64.binascii.Error, ValueError):
                                    logger.warning(
                                        "Failed to base64-decode inline image data in combined call"
                                    )
                    # JSON text metadata
                    if hasattr(part, "text") and part.text:
                        json_text = part.text
                        parsed = extract_json_metadata(json_text)
                        if parsed:
                            metadata = parsed
                            logger.debug("Found metadata in response")

        # If image_bytes is missing, check for error JSON and log structured debug info
        if image_bytes is None:
            # Build structured debug payload
            debug_info = {
                "parts_count": 0,
                "part_types": [],
                "has_text": False,
                "has_inline_data": False,
                "text_preview": None,
            }
            
            if hasattr(resp, "candidates") and resp.candidates:
                candidate = resp.candidates[0]
                if (
                    hasattr(candidate, "content")
                    and candidate.content is not None
                    and hasattr(candidate.content, "parts")
                    and candidate.content.parts is not None
                ):
                    parts = candidate.content.parts
                    debug_info["parts_count"] = len(parts)
                    debug_info["part_types"] = [type(p).__name__ for p in parts]
                    debug_info["has_text"] = any(hasattr(p, "text") and p.text for p in parts)
                    debug_info["has_inline_data"] = any(
                        hasattr(p, "inline_data") and getattr(p, "inline_data", None) is not None
                        for p in parts
                    )
                    # Get first text part preview
                    for part in parts:
                        if hasattr(part, "text") and part.text:
                            debug_info["text_preview"] = str(part.text)[:300]
                            break
            
            logger.warning(
                "No IMAGE part returned by Gemini in combined call. "
                f"Debug info: {debug_info}. Falling back to image-only generation."
            )
            
            # Check if JSON contains error response
            if json_text:
                parsed_error = extract_json_metadata(json_text)
                if isinstance(parsed_error, dict) and parsed_error.get("error") == "no_image_generated":
                    logger.warning(
                        f"Gemini explicitly reported image generation failure: {parsed_error.get('reason', 'unknown')}"
                    )
                    # Still try fallback even if error JSON is present
                    # metadata will be the error dict
            
            # Fallback: use image-only generation method
            try:
                image_bytes = await self.generate_product_image_from_outfit(
                    item_name=item_name,
                    outfit_image=outfit_image
                )
                logger.info("Fallback image generation succeeded")
            except Exception as e:
                logger.error(f"Fallback image generation also failed: {e}")
                # If we have metadata from the combined call, return it with None image
                if metadata:
                    return None, metadata
                # Otherwise raise
                raise ValueError(f"Could not generate image via combined call or fallback: {e}")

        # On JSON failure, metadata will be {} as per extractor
        return image_bytes, metadata


# Module-level singleton instance
_ai_provider: Optional[AIProvider] = None


def get_ai_provider() -> AIProvider:
    """Get or create the singleton AI provider instance."""
    global _ai_provider
    if _ai_provider is None:
        _ai_provider = AIProvider()
    return _ai_provider

