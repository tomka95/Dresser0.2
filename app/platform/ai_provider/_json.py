"""JSON extraction from raw model text (structured-output parsing helper)."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


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
