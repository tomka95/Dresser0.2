"""Normalize and split Gemini analysis output into colors and tags.

This module provides functions to:
1. Normalize Gemini JSON responses into a consistent internal structure
2. Classify free-text labels into colors vs tags using deterministic rules
3. Handle color variations, patterns, and materials correctly
"""

import re
from typing import Any, Dict, List, Optional, Tuple


# Comprehensive color dictionary including tricky color-like words
COLOR_DICTIONARY = {
    # Basic colors
    "black", "white", "red", "blue", "green", "yellow", "orange", "purple", "pink",
    "brown", "gray", "grey",
    # Extended colors
    "beige", "cream", "ivory", "off-white", "offwhite", "charcoal", "navy", "teal",
    "maroon", "burgundy", "olive", "khaki", "tan", "cobalt", "coral", "turquoise",
    "lavender", "gold", "silver", "bronze", "copper", "salmon", "mint", "lime",
    "cyan", "magenta", "indigo", "violet", "amber", "peach", "rose", "sage",
    # Shades and modifiers (will be combined with base colors)
    "light", "dark", "pale", "bright", "deep", "vivid", "muted", "soft", "rich",
    "dull", "faded", "neon", "pastel", "electric", "neon",
}

# Pattern/material keywords that should be tags, NOT colors
PATTERN_MATERIAL_KEYWORDS = {
    "striped", "stripes", "floral", "plaid", "checkered", "polka", "dot", "dots",
    "leopard", "zebra", "camo", "camouflage", "denim", "leather", "suede", "velvet",
    "silk", "cotton", "wool", "linen", "polyester", "spandex", "lycra", "mesh",
    "knit", "woven", "embroidered", "printed", "patterned", "solid", "textured",
    "sequined", "beaded", "lace", "ruffled", "pleated", "gathered", "tiered",
}

# Color modifiers that can appear before base colors
COLOR_MODIFIERS = {
    "light", "dark", "pale", "bright", "deep", "vivid", "muted", "soft", "rich",
    "dull", "faded", "neon", "pastel", "electric", "off", "navy", "royal", "sky",
    "forest", "lime", "mint", "sage", "olive", "khaki", "tan", "beige", "cream",
    "ivory", "charcoal", "teal", "maroon", "burgundy", "cobalt", "coral",
    "turquoise", "lavender", "salmon", "peach", "rose", "amber",
}

# Base colors (without modifiers)
BASE_COLORS = {
    "black", "white", "red", "blue", "green", "yellow", "orange", "purple", "pink",
    "brown", "gray", "grey", "beige", "cream", "ivory", "charcoal", "navy", "teal",
    "maroon", "burgundy", "olive", "khaki", "tan", "cobalt", "coral", "turquoise",
    "lavender", "gold", "silver", "bronze", "copper", "salmon", "mint", "lime",
    "cyan", "magenta", "indigo", "violet", "amber", "peach", "rose", "sage",
}


def normalize_label(text: str) -> str:
    """Normalize a label string for comparison and deduplication.
    
    Args:
        text: Raw label text
        
    Returns:
        Normalized string (lowercase, trimmed, spaces normalized)
    """
    if not text:
        return ""
    # Convert to lowercase, strip, and normalize whitespace
    normalized = re.sub(r'\s+', ' ', text.strip().lower())
    return normalized


def extract_structured_palette(analysis_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract structured color/palette fields from Gemini JSON if present.
    
    Looks for common fields like:
    - colors (list of color objects)
    - palette (list of color objects)
    - color_palette (list of color objects)
    - dominant_colors (list of color objects)
    
    Each color object may have: name, hex, score, confidence, etc.
    
    Args:
        analysis_json: Raw Gemini JSON response
        
    Returns:
        List of color dicts with normalized structure: [{"name": str, "score": float|None, "hex": str|None}]
    """
    colors = []
    
    # Try various possible field names
    color_fields = ["colors", "palette", "color_palette", "dominant_colors", "color_list"]
    
    for field in color_fields:
        if field in analysis_json:
            value = analysis_json[field]
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        color_name = item.get("name") or item.get("color") or item.get("label")
                        if color_name:
                            colors.append({
                                "name": str(color_name).strip(),
                                "score": item.get("score") or item.get("confidence") or item.get("probability"),
                                "hex": item.get("hex") or item.get("hex_code") or item.get("color_hex"),
                            })
                    elif isinstance(item, str):
                        colors.append({
                            "name": item.strip(),
                            "score": None,
                            "hex": None,
                        })
    
    return colors


def extract_candidate_labels(analysis_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract all candidate labels from Gemini JSON response.
    
    Looks for various possible fields:
    - labels (list of strings or objects)
    - tags (list of strings or objects)
    - attributes (list of strings or objects)
    - description (string that may contain labels)
    - text_labels (list)
    
    Args:
        analysis_json: Raw Gemini JSON response
        
    Returns:
        List of label dicts: [{"text": str, "score": float|None}]
    """
    labels = []
    
    # Try various possible field names
    label_fields = ["labels", "tags", "attributes", "text_labels", "detected_labels"]
    
    for field in label_fields:
        if field in analysis_json:
            value = analysis_json[field]
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        label_text = item.get("text") or item.get("label") or item.get("name") or item.get("value")
                        if label_text:
                            labels.append({
                                "text": str(label_text).strip(),
                                "score": item.get("score") or item.get("confidence") or item.get("probability"),
                            })
                    elif isinstance(item, str):
                        labels.append({
                            "text": item.strip(),
                            "score": None,
                        })
    
    # Also check description field for comma-separated or space-separated labels
    if "description" in analysis_json:
        desc = analysis_json["description"]
        if isinstance(desc, str):
            # Try to extract labels from description
            # Split on commas or common separators
            parts = re.split(r'[,;]|\s+and\s+', desc, flags=re.IGNORECASE)
            for part in parts:
                part = part.strip()
                if part and len(part) > 2:
                    labels.append({
                        "text": part,
                        "score": None,
                    })
    
    return labels


def split_combined_color_string(text: str) -> List[str]:
    """Split combined color strings like "black and white", "black/white", "navy blue".
    
    Args:
        text: Combined color string
        
    Returns:
        List of individual color strings
    """
    if not text:
        return []
    
    text_lower = text.lower().strip()
    
    # Split on " and ", " & ", "/", ","
    separators = [r'\s+and\s+', r'\s+&\s+', r'\s*/\s*', r'\s*,\s*']
    
    for sep in separators:
        if re.search(sep, text_lower):
            parts = re.split(sep, text_lower)
            return [p.strip() for p in parts if p.strip()]
    
    # Check for compound colors like "navy blue", "off white", "light blue"
    # These should be kept as single units if they match known patterns
    return [text_lower]


def is_color_label(text: str) -> bool:
    """Determine if a label string represents a color (not a pattern/material).
    
    Uses normalization, color dictionary, and regex rules.
    
    Args:
        text: Label text to classify
        
    Returns:
        True if the label is a color, False if it's a tag
    """
    if not text:
        return False
    
    normalized = normalize_label(text)
    
    # Check if it's a known pattern/material (these are NEVER colors)
    words = set(normalized.split())
    if words & PATTERN_MATERIAL_KEYWORDS:
        return False
    
    # Check for color modifier + base color pattern (e.g., "light blue", "dark red")
    modifier_base_pattern = r'^(light|dark|pale|bright|deep|vivid|muted|soft|rich|dull|faded|neon|pastel|electric|off)\s+(blue|red|green|yellow|orange|purple|pink|brown|gray|grey|white|black|beige|cream|ivory|charcoal|navy|teal|maroon|burgundy|olive|khaki|tan|cobalt|coral|turquoise|lavender|salmon|peach|rose|amber|mint|lime|sage)$'
    if re.match(modifier_base_pattern, normalized):
        return True
    
    # Check if normalized text is in color dictionary
    if normalized in COLOR_DICTIONARY:
        return True
    
    # Check if any word in the text is a base color
    words = normalized.split()
    for word in words:
        if word in BASE_COLORS:
            # Make sure it's not a pattern/material context
            if not (words & PATTERN_MATERIAL_KEYWORDS):
                return True
    
    # Special cases: compound colors that should be recognized
    compound_colors = {
        "navy blue", "off white", "off-white", "light blue", "dark blue", "royal blue",
        "sky blue", "forest green", "lime green", "mint green", "sage green",
        "olive green", "khaki green", "tan brown", "beige brown", "cream white",
        "ivory white", "charcoal gray", "teal blue", "maroon red", "burgundy red",
        "cobalt blue", "coral pink", "turquoise blue", "lavender purple", "salmon pink",
        "peach orange", "rose pink", "amber yellow",
    }
    
    if normalized in compound_colors:
        return True
    
    return False


def split_labels_into_colors_and_tags(
    labels: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split a list of labels into colors and tags.
    
    Args:
        labels: List of label dicts with {"text": str, "score": float|None}
        
    Returns:
        Tuple of (colors, tags) where each is a list of dicts:
        - colors: [{"name": str, "score": float|None, "hex": str|None}]
        - tags: [{"name": str, "score": float|None}]
    """
    colors = []
    tags = []
    
    for label in labels:
        text = label.get("text", "")
        if not text:
            continue
        
        score = label.get("score")
        
        # Split combined color strings first
        split_colors = split_combined_color_string(text)
        
        # Process each split color
        for color_text in split_colors:
            if is_color_label(color_text):
                colors.append({
                    "name": color_text,
                    "score": score,
                    "hex": None,  # Will be filled from structured palette if available
                })
            else:
                # Check if it contains both color and pattern words
                # If so, extract both
                words = set(normalize_label(color_text).split())
                color_words = words & BASE_COLORS
                pattern_words = words & PATTERN_MATERIAL_KEYWORDS
                
                if color_words and pattern_words:
                    # Extract colors
                    for color_word in color_words:
                        colors.append({
                            "name": color_word,
                            "score": score,
                            "hex": None,
                        })
                    # Extract patterns as tags
                    for pattern_word in pattern_words:
                        tags.append({
                            "name": pattern_word,
                            "score": score,
                        })
                    # Also add the full text as a tag if it's descriptive
                    if len(words) > len(color_words | pattern_words):
                        tags.append({
                            "name": color_text,
                            "score": score,
                        })
                else:
                    # Not a color, so it's a tag
                    tags.append({
                        "name": color_text,
                        "score": score,
                    })
    
    # Deduplicate colors and tags, keeping max score
    colors = dedupe_keep_max_score(colors, "name")
    tags = dedupe_keep_max_score(tags, "name")
    
    # Sort by score descending (None scores go last)
    colors.sort(key=lambda x: (x["score"] is None, -(x["score"] or 0)), reverse=False)
    tags.sort(key=lambda x: (x["score"] is None, -(x["score"] or 0)), reverse=False)
    
    return colors, tags


def dedupe_keep_max_score(items: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    """Deduplicate items by normalized key, keeping the one with the maximum score.
    
    Args:
        items: List of dicts to deduplicate
        key: Key to use for deduplication (will be normalized)
        
    Returns:
        Deduplicated list, preserving order by score (descending)
    """
    seen = {}
    
    for item in items:
        key_value = item.get(key, "")
        normalized_key = normalize_label(str(key_value))
        
        if normalized_key not in seen:
            seen[normalized_key] = item
        else:
            # Keep the one with higher score
            existing_score = seen[normalized_key].get("score")
            current_score = item.get("score")
            
            # None scores are treated as 0
            existing_val = existing_score if existing_score is not None else 0
            current_val = current_score if current_score is not None else 0
            
            if current_val > existing_val:
                seen[normalized_key] = item
    
    return list(seen.values())


def normalize_json_analysis(analysis_json: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize AI analysis JSON into a consistent internal structure.
    
    This function is resilient and handles:
    - Missing keys
    - Unknown shapes
    - Different AI response formats
    - Structured color/palette fields
    - Free-text labels
    
    Args:
        analysis_json: Raw AI JSON response (can be any shape)
        
    Returns:
        Dict with:
        - colors: List[{"name": str, "score": float|None, "hex": str|None}]
        - tags: List[{"name": str, "score": float|None}]
        - raw_labels: List[{"text": str, "score": float|None}] (flattened candidate labels)
    """
    if not isinstance(analysis_json, dict):
        analysis_json = {}
    
    # Extract structured palette colors first (these take precedence)
    structured_colors = extract_structured_palette(analysis_json)
    
    # Extract candidate labels from various fields
    candidate_labels = extract_candidate_labels(analysis_json)
    
    # Combine structured colors with candidate labels
    # Convert structured colors to label format for processing
    all_labels = []
    
    # Add structured colors as labels (they're already colors, so mark them)
    for color in structured_colors:
        all_labels.append({
            "text": color["name"],
            "score": color["score"],
            "_is_color": True,  # Internal flag
            "_hex": color.get("hex"),
        })
    
    # Add candidate labels
    for label in candidate_labels:
        all_labels.append(label)
    
    # Split labels into colors and tags
    colors, tags = split_labels_into_colors_and_tags(all_labels)
    
    # Merge hex codes from structured colors back into the colors list
    hex_map = {normalize_label(c["name"]): c.get("hex") for c in structured_colors if c.get("hex")}
    for color in colors:
        normalized_name = normalize_label(color["name"])
        if normalized_name in hex_map:
            color["hex"] = hex_map[normalized_name]
    
    return {
        "colors": colors,
        "tags": tags,
        "raw_labels": candidate_labels,
    }

