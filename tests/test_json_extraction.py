"""Unit tests for JSON extraction helper used with Gemini responses."""

from app.services.ai_provider import extract_json_metadata


def test_extract_json_metadata_raw_json():
    """Raw JSON string should be parsed into a dict."""
    text = '{"name": "Red Nike T-Shirt", "brand": "Nike"}'
    result = extract_json_metadata(text)
    assert isinstance(result, dict)
    assert result["name"] == "Red Nike T-Shirt"
    assert result["brand"] == "Nike"


def test_extract_json_metadata_fenced_json():
    """```json fenced content should be unwrapped and parsed."""
    text = """```json
{"name": "Red Nike T-Shirt", "brand": "Nike"}
```"""
    result = extract_json_metadata(text)
    assert isinstance(result, dict)
    assert result["name"] == "Red Nike T-Shirt"
    assert result["brand"] == "Nike"


def test_extract_json_metadata_invalid_json():
    """Invalid JSON should return an empty dict instead of raising."""
    text = "not valid json at all"
    result = extract_json_metadata(text)
    assert result == {}





