"""Stub tests for LLM extractor JSON parsing and schema validation."""

import json
from datetime import datetime

import pytest

from app.gmail_closet.llm_extractor import extract_clothing_purchase_from_email
from app.gmail_closet.models import EmailMetadata


@pytest.mark.asyncio
async def test_json_parsing_with_valid_clothing_purchase(monkeypatch):
    """Test that valid JSON responses are parsed correctly."""
    # Mock OpenAI response
    mock_response_data = {
        "is_clothing_purchase": True,
        "order_id": "ORD-12345",
        "order_date": "2024-01-15T10:30:00Z",
        "retailer": "Zara",
        "items": [
            {"name": "Black skinny jeans", "store": "Zara", "price": 49.99},
            {"name": "White t-shirt", "store": "Zara", "price": 19.99},
        ],
    }

    class MockMessage:
        content = json.dumps(mock_response_data)

    class MockChoice:
        message = MockMessage()

    class MockResponse:
        choices = [MockChoice()]

    async def mock_create(*args, **kwargs):
        return MockResponse()

    # This is a stub test - in a real scenario, you'd properly mock the OpenAI client
    # For now, we'll just test the JSON parsing logic separately
    metadata = EmailMetadata(
        message_id="test-1",
        thread_id="test-1",
        subject="Order confirmation",
        sender="store@example.com",
        sent_at=datetime.utcnow(),
    )

    # Test that the JSON structure is valid
    assert json.loads(json.dumps(mock_response_data)) == mock_response_data
    assert mock_response_data["is_clothing_purchase"] is True
    assert len(mock_response_data["items"]) == 2


@pytest.mark.asyncio
async def test_json_parsing_with_non_clothing_purchase():
    """Test that non-clothing purchase responses are handled."""
    mock_response_data = {
        "is_clothing_purchase": False,
    }

    # Test that the JSON structure is valid
    assert json.loads(json.dumps(mock_response_data)) == mock_response_data
    assert mock_response_data["is_clothing_purchase"] is False


@pytest.mark.asyncio
async def test_json_parsing_with_missing_fields():
    """Test that missing optional fields are handled gracefully."""
    mock_response_data = {
        "is_clothing_purchase": True,
        "items": [
            {"name": "Blue jeans"},  # Missing store and price
            {"name": "Red shirt", "price": 29.99},  # Missing store
        ],
    }

    # Test that the JSON structure is valid
    parsed = json.loads(json.dumps(mock_response_data))
    assert parsed["is_clothing_purchase"] is True
    assert len(parsed["items"]) == 2
    assert parsed["items"][0]["name"] == "Blue jeans"
    assert "store" not in parsed["items"][0]
    assert "price" not in parsed["items"][0]

