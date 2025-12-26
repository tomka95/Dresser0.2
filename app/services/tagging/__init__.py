"""Tagging services for normalizing and splitting colors and tags."""

from .normalize_and_split import (
    normalize_gemini_analysis,
    split_labels_into_colors_and_tags,
    normalize_label,
    extract_candidate_labels,
    extract_structured_palette,
    dedupe_keep_max_score,
)

__all__ = [
    "normalize_gemini_analysis",
    "split_labels_into_colors_and_tags",
    "normalize_label",
    "extract_candidate_labels",
    "extract_structured_palette",
    "dedupe_keep_max_score",
]

