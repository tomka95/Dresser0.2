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
                model="gemini-1.5-flash",
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
                model="gemini-1.5-flash",
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
                model="gemini-1.5-flash",
                contents=parts
            )
        )
        
        if hasattr(resp, "candidates") and resp.candidates:
            candidate = resp.candidates[0]
            if hasattr(candidate, "content") and hasattr(candidate.content, "parts"):
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
    ) -> Tuple[bytes, Dict[str, Any]]:
        """
        Single-call flow that generates a product image and JSON metadata.

        Uses the Gemini image model with multimodal output (TEXT + IMAGE).
        """
        # Determine MIME type from format or default to jpeg
        mime_type = "image/jpeg"
        if getattr(outfit_image, "format", None):
            format_lower = outfit_image.format.lower()
            if format_lower in ["png", "jpg", "jpeg"]:
                mime_type = f"image/{format_lower if format_lower != 'jpg' else 'jpeg'}"

        prompt = f"{json_prompt}\n\nReturn JSON ONLY in the text part. No markdown or commentary."

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

        if hasattr(resp, "candidates") and resp.candidates:
            candidate = resp.candidates[0]
            if hasattr(candidate, "content") and hasattr(candidate.content, "parts"):
                for part in candidate.content.parts:
                    # Image bytes via inline_data
                    if getattr(part, "inline_data", None) and getattr(
                        part.inline_data, "data", None
                    ) is not None:
                        data = part.inline_data.data
                        if isinstance(data, bytes):
                            image_bytes = data
                        elif isinstance(data, str):
                            try:
                                image_bytes = base64.b64decode(data)
                            except (base64.binascii.Error, ValueError):
                                logger.warning(
                                    "Failed to base64-decode inline image data in combined call"
                                )
                    # JSON text metadata
                    if getattr(part, "text", None):
                        parsed = extract_json_metadata(part.text)
                        if parsed:
                            metadata = parsed

        if image_bytes is None:
            raise ValueError("Could not extract image bytes from Gemini combined response")

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

