"""Unit tests for filename sanitization in the clothing pipeline."""

from app.services.clothing_pipeline import sanitize_filename


def test_sanitize_filename_basic():
    """Spaces should become underscores and basic text should be preserved."""
    assert sanitize_filename("Red Nike T-Shirt") == "Red_Nike_T-Shirt"


def test_sanitize_filename_strips_quotes_and_invalid_chars():
    """Quotes and invalid filesystem characters should be removed."""
    original = '"Blue/Green: Jacket*?<>|\\n"'
    sanitized = sanitize_filename(original)
    assert '"' not in sanitized
    assert "/" not in sanitized
    assert ":" not in sanitized
    assert "*" not in sanitized
    assert "?" not in sanitized
    assert "<" not in sanitized
    assert ">" not in sanitized
    assert "|" not in sanitized


def test_sanitize_filename_empty_fallback():
    """Empty or whitespace-only names should fall back to 'item'."""
    assert sanitize_filename("   ") == "item"


