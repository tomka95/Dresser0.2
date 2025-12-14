"""AI provider abstraction layer for supporting multiple LLM providers (Gemini, OpenAI, etc.)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from functools import partial
from typing import Any, Dict, List, Optional

from google import genai

from app.core.config import settings


@dataclass
class DetectedItem:
    """Represents a detected clothing item."""
    name: str


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
        
        try:
            # Try to extract JSON from the response (might be wrapped in markdown code blocks)
            if "```json" in response_text:
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                response_text = response_text[start:end].strip()
            elif "```" in response_text:
                start = response_text.find("```") + 3
                end = response_text.find("```", start)
                response_text = response_text[start:end].strip()
            
            metadata = json.loads(response_text)
            return metadata if isinstance(metadata, dict) else {}
        except (json.JSONDecodeError, ValueError) as e:
            # Return empty dict if JSON parsing fails
            return {}
    
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
        
        # TODO: Extract raw image bytes from the response
        # The exact structure depends on Gemini's response format for image generation
        # For now, this is a placeholder that will need to be implemented based on
        # the actual response structure from Gemini's image generation API
        # Expected structure might be something like:
        # resp.candidates[0].content.parts[0].inline_data.data
        # or similar, depending on the actual API response
        
        # Placeholder - this will need to be updated once we know the exact response format
        if hasattr(resp, 'candidates') and resp.candidates:
            candidate = resp.candidates[0]
            if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                for part in candidate.content.parts:
                    if hasattr(part, 'inline_data') and hasattr(part.inline_data, 'data'):
                        return part.inline_data.data
        
        # Fallback: raise an error if we can't extract the image
        raise ValueError("Could not extract image bytes from Gemini response")


# Module-level singleton instance
_ai_provider: Optional[AIProvider] = None


def get_ai_provider() -> AIProvider:
    """Get or create the singleton AI provider instance."""
    global _ai_provider
    if _ai_provider is None:
        _ai_provider = AIProvider()
    return _ai_provider

