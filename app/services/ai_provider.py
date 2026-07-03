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

    def generate_structured(
        self,
        *,
        model: str,
        system_instruction: str,
        user_text: str,
        response_schema: Any,
        image_parts: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.0,
        media_resolution: Optional[Any] = None,
    ):
        """Synchronous structured-output generation (the phase-3c receipt extractor).

        Forces valid typed JSON via responseMimeType=application/json + responseSchema,
        so the caller NEVER regexes the model output. Returns the raw
        GenerateContentResponse so the caller can read `.parsed` / `.text` and
        `.usage_metadata` (for cost instrumentation).

        Kept synchronous on purpose: the extraction pass mirrors the 3b fetch
        service (sync, ThreadPoolExecutor), so a blocking SDK call inside a worker
        thread is the right shape. This reuses the single Gemini SDK path; it does
        NOT add a new provider integration.

        `system_instruction` and `user_text` are kept separate so untrusted email
        content (user_text) can never be confused with the extraction rules
        (system_instruction) — the prompt-injection boundary.
        """
        contents_parts: List[Any] = []
        if image_parts:
            contents_parts.extend(image_parts)
        contents_parts.append({"text": user_text})

        config_kwargs: Dict[str, Any] = dict(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=response_schema,
            temperature=temperature,
        )
        # media_resolution=LOW lets the vision-verify pass pay for color+garment
        # recognition without OCR-grade token cost. Optional / additive.
        if media_resolution is not None:
            config_kwargs["media_resolution"] = media_resolution
        config = types.GenerateContentConfig(**config_kwargs)
        return self._client.models.generate_content(
            model=model,
            contents=contents_parts,
            config=config,
        )

    def embed_texts(
        self,
        texts: List[str],
        *,
        model: str,
        dim: int,
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> List[List[float]]:
        """Embed one or more short product strings to fixed-width vectors.

        Wave S0 Branch B: the item-embedding seam. Synchronous (mirrors
        generate_structured — enrichment runs in a background thread, so a blocking
        SDK call is the right shape). `output_dimensionality=dim` pins the width to
        the vector(dim) column declared in migration 0018 (768; gemini-embedding-001's
        native width is 3072, truncated via MRL). `task_type=RETRIEVAL_DOCUMENT` is
        correct for indexing closet
        items; a query-time embed would pass RETRIEVAL_QUERY.

        The input is product attribute text ONLY (brand/subcategory/color/pattern/…),
        never image bytes or PII — see app/services/embeddings.build_canonical_text.
        Returns one vector per input, in order. Raises on API failure (the caller —
        enrich_item — swallows it so a transient embed miss never breaks enrichment).
        """
        if not texts:
            return []
        resp = self._client.models.embed_content(
            model=model,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=dim,
            ),
        )
        # google-genai returns .embeddings[i].values (list[float]) per input.
        return [list(e.values) for e in resp.embeddings]

    async def detect_clothing_items_from_image(
        self,
        outfit_image,
        *,
        max_items: int = 10
    ) -> Dict[str, Dict[str, Any]]:
        """
        Detect clothing items from an outfit image.
        
        Args:
            outfit_image: Image object with `.data` (bytes) and `.format` (str or None)
            max_items: Maximum number of items to detect
            
        Returns:
            Dictionary where keys are item display names (strings) and values are
            metadata dictionaries containing fields like name, brand, category,
            sub_category, color, pattern, material, fit, style, season, gender,
            tags, confidence, and notes. Returns empty dict if parsing fails.
        """
        # Build prompt for Gemini demanding JSON object with specific schema
        prompt = f"""Look at this outfit photo and identify up to {max_items} clothing items you can see and only from the main person in the image.

STRICT REQUIREMENT: Return ONLY wearable CLOTHING garments (e.g., tops, bottoms, dresses, outerwear, and shoes/footwear (sneakers, boots, heels, sandals)) worn by the main person in the image.
EXCLUDE: jewelry, watches, bags, hats, sunglasses, phones, earbuds, props, background objects, furniture.
Shoes/footwear ARE clothing and must be included if present.
If you are unsure whether something is clothing, you MUST omit it. Only include items that are clearly wearable garments.

You MUST return a JSON object (not an array, not markdown, JSON only) where:
- Each key is an item display name (string)
- Each value is a metadata object (dict) containing as many of these fields as possible:
  - name (string; should match the key closely)
  - is_clothing (boolean; MUST always be true for all items)
  - brand (string or null)
  - category (string or null, e.g., "tops", "bottoms", "shoes", "outerwear")
  - sub_category (string or null, e.g., "t-shirt", "jeans", "sneakers")
  - color (string or null)
  - pattern (string or null, e.g., "solid", "striped", "floral")
  - material (string or null, e.g., "cotton", "denim", "leather")
  - fit (string or null, e.g., "slim", "regular", "loose")
  - style (string or null, e.g., "casual", "formal", "sporty")
  - season (string or null, e.g., "spring", "summer", "fall", "winter", "all-season")
  - gender (string or null, e.g., "men", "women", "unisex")
  - tags (array of strings; can be empty)
  - confidence (number 0-1 or null)
  - notes (string or null)

Return ONLY valid JSON, no markdown fences, no explanatory text, just the JSON object.
Example format:
{{
  "Blue T-Shirt": {{
    "name": "Blue T-Shirt",
    "is_clothing": true,
    "brand": null,
    "category": "tops",
    "sub_category": "t-shirt",
    "color": "blue",
    "pattern": "solid",
    "material": "cotton",
    "fit": "regular",
    "style": "casual",
    "season": "all-season",
    "gender": "unisex",
    "tags": ["casual", "comfortable"],
    "confidence": 0.95,
    "notes": null
  }},
  "Denim Jeans": {{
    "name": "Denim Jeans",
    "is_clothing": true,
    "brand": null,
    "category": "bottoms",
    "sub_category": "jeans",
    "color": "blue",
    "pattern": "solid",
    "material": "denim",
    "fit": "slim",
    "style": "casual",
    "season": "all-season",
    "gender": "unisex",
    "tags": ["denim", "casual"],
    "confidence": 0.92,
    "notes": null
  }}
}}
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
        # Using gemini-2.5-flash-lite for text-only JSON output (cheaper than flash-image)
        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(
            None,
            partial(
                self._client.models.generate_content,
                model="gemini-2.5-flash-lite",
                contents=parts
            )
        )
        
        # Extract and parse response
        response_text = resp.text.strip()
        
        # Parse JSON using the existing helper
        parsed = extract_json_metadata(response_text)
        
        # Validate the parsed result
        if not isinstance(parsed, dict):
            logger.warning("Parsed result is not a dict, returning empty dict")
            return {}
        
        # Ensure each value is a dict (coerce to {} if not) and add is_clothing field
        validated: Dict[str, Dict[str, Any]] = {}
        for key, value in parsed.items():
            if isinstance(value, dict):
                # Ensure is_clothing is always true for all items
                value["is_clothing"] = True
                validated[str(key)] = value
            else:
                logger.warning(f"Value for key '{key}' is not a dict, coercing to empty dict")
                validated[str(key)] = {"is_clothing": True}
        
        # Limit to max_items (preserve order)
        if len(validated) > max_items:
            # Convert to list of items, slice, then reconstruct dict to preserve order
            items_list = list(validated.items())[:max_items]
            validated = dict(items_list)
        
        return validated
    
    
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

    async def generate_product_images_from_outfit_batch(
        self,
        outfit_image,
        *,
        item_names: List[str]
    ) -> Dict[str, bytes]:
        """
        Generate multiple product images from an outfit photo in a single call.
        
        Args:
            outfit_image: Image object with `.data` (bytes) and `.format` (str or None)
            item_names: Ordered list of item names to generate images for
            
        Returns:
            Dictionary mapping item names to image bytes. Returns empty dict if no images.
        """
        if not item_names:
            return {}
        
        expected_count = len(item_names)
        
        # Create numbered list string for clarity
        items_name_list_str = "\n".join(f"{i+1}. {name}" for i, name in enumerate(item_names))
        logger.info(f"Items name list string: {items_name_list_str}")
        # Create JSON array string for the prompt
        items_json_array_str = json.dumps(item_names, ensure_ascii=False)
        logger.info(f"Items JSON array string: {items_json_array_str}")
        # Build prompt with explicit count and multiple format references
        prompt = f"""Look at this outfit photo and create e-commerce product images. 

IMPORTANT: The list below contains ONLY clothing items. Do NOT generate images for accessories, jewelry, or objects.
Shoes/footwear ARE clothing. If 'sneakers/boots/heels/sandals' appear in the list, generate them like any other item.

TASK: Generate exactly {expected_count} separate, isolated product photos.

ITEMS TO GENERATE (in this exact order):
{items_name_list_str}

JSON array format: {items_json_array_str}

If any listed item is not clothing, skip it and do NOT output an image for it. Keep the JSON order only for items you will generate.

For EACH item, create a professional e-commerce product image with:
- Pure white (#FFFFFF) background
- ONLY the single item isolated (no model/body, no other items, no scene, no text)
- For shoes, generate the pair (if a pair is visible/expected), isolated on white.
- Centered and well-lit
- Professional product photography style

STRICT OUTPUT REQUIREMENTS:

1) FIRST OUTPUT: Return a JSON text part (JSON only, no markdown, no code fences) with this exact format:
   {{"order": {items_json_array_str}}}
   The "order" array must contain exactly these {expected_count} items in this exact order: {items_json_array_str}

2) THEN OUTPUT: Return exactly {expected_count} IMAGE parts, one per item, in the same order as the "order" array.
   - Image #1 = first item in "order" array
   - Image #2 = second item in "order" array
   - Image #3 = third item in "order" array
   - ... and so on for all {expected_count} items

CRITICAL: You must return exactly {expected_count} images, one per item listed above. Each image must contain ONLY the single item unfolded on a pure white background; no model/body, no other items, no scene, no text.

Return ONLY the JSON first, then exactly {expected_count} images in order. No other text or explanation.
"""
        
        # Determine MIME type from format or default to jpeg
        mime_type = "image/jpeg"
        if getattr(outfit_image, "format", None):
            format_lower = outfit_image.format.lower()
            if format_lower in ["png", "jpg", "jpeg"]:
                mime_type = f"image/{format_lower if format_lower != 'jpg' else 'jpeg'}"
        
        # Prepare multimodal request parts
        parts = [
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": outfit_image.data,
                }
            },
            {"text": prompt},
        ]
        
        # Run Gemini call in thread executor with TEXT + IMAGE modalities
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
        
        # Extract JSON text part and image parts
        json_text: Optional[str] = None
        image_parts: List[bytes] = []
        
        if hasattr(resp, "candidates") and resp.candidates:
            candidate = resp.candidates[0]
            if (
                hasattr(candidate, "content")
                and candidate.content is not None
                and hasattr(candidate.content, "parts")
                and candidate.content.parts is not None
            ):
                response_parts = candidate.content.parts
                for part in response_parts:
                    # Extract JSON text part (should be first)
                    if hasattr(part, "text") and part.text:
                        if json_text is None:  # Take first text part as JSON
                            json_text = part.text
                            logger.debug("Found JSON text part in batch response")
                    
                    # Extract image parts
                    if hasattr(part, "inline_data") and hasattr(part.inline_data, "data"):
                        data = part.inline_data.data
                        if data is not None:
                            if isinstance(data, bytes):
                                image_parts.append(data)
                                logger.debug(f"Found image bytes (bytes, length: {len(data)})")
                            elif isinstance(data, str):
                                try:
                                    decoded = base64.b64decode(data)
                                    image_parts.append(decoded)
                                    logger.debug(f"Found image bytes (base64 string, decoded length: {len(decoded)})")
                                except (base64.binascii.Error, ValueError):
                                    logger.warning("Failed to base64-decode inline image data in batch call")
        
        # Parse JSON to get order array
        order: List[str] = item_names  # Fallback to original order
        if json_text:
            parsed = extract_json_metadata(json_text)
            if isinstance(parsed, dict) and "order" in parsed:
                parsed_order = parsed["order"]
                if isinstance(parsed_order, list) and len(parsed_order) == len(image_parts):
                    # Validate that all items in order are strings
                    if all(isinstance(item, str) for item in parsed_order):
                        order = parsed_order
                        logger.debug(f"Using order from JSON: {order}")
                    else:
                        logger.warning("Order array contains non-string values, using fallback order")
                else:
                    logger.warning(
                        f"Order array length ({len(parsed_order) if isinstance(parsed_order, list) else 'N/A'}) "
                        f"does not match image count ({len(image_parts)}), using fallback order"
                    )
            else:
                logger.warning("JSON does not contain valid 'order' array, using fallback order")
        
        # Map images to item names by order
        result: Dict[str, bytes] = {}
        for i, image_bytes in enumerate(image_parts):
            if i < len(order):
                item_name = order[i]
                result[item_name] = image_bytes
                logger.debug(f"Mapped image {i+1} to item '{item_name}'")
            else:
                logger.warning(f"More images ({len(image_parts)}) than items ({len(order)}), skipping extra image {i+1}")
        
        if result:
            logger.info(f"Generated {len(result)} product images from batch call for items: {list(result.keys())}")
        else:
            logger.warning("No images generated in batch call")
        
        return result


# Module-level singleton instance
_ai_provider: Optional[AIProvider] = None


def get_ai_provider() -> AIProvider:
    """Get or create the singleton AI provider instance."""
    global _ai_provider
    if _ai_provider is None:
        _ai_provider = AIProvider()
    return _ai_provider

