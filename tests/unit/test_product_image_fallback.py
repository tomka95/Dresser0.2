"""Unit tests for product image fallback generation.

Note (phase 3a): two tests that exercised the deleted regex pipeline's writer
(app.gmail_closet.email_clothing_service.save_email_items_for_user) were removed
when that module was deleted. The tests below cover the still-live
app.services.product_image_fallback.generate_product_packshot service.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from uuid import uuid4

from app.services.product_image_fallback import generate_product_packshot


@pytest.mark.asyncio
async def test_generate_product_packshot_success():
    """Test successful packshot generation and upload."""
    shop_name = "Zara"
    item_name = "Blue T-Shirt"

    # Mock image bytes from Gemini
    mock_image_bytes = b"fake_image_data"

    # Mock Gemini response
    mock_candidate = MagicMock()
    mock_part = MagicMock()
    mock_part.inline_data.data = mock_image_bytes
    mock_candidate.content.parts = [mock_part]
    mock_resp = MagicMock()
    mock_resp.candidates = [mock_candidate]

    # Mock Supabase storage
    mock_storage_client = MagicMock()
    mock_storage_client.upload_bytes.return_value = "https://supabase.com/bucket/generated/Zara/Blue_T_Shirt-abc12345.png"

    with patch("app.services.product_image_fallback.get_ai_provider") as mock_get_ai, \
         patch("app.services.product_image_fallback.SupabaseStorageClient") as mock_storage_class:

        # Setup AI provider mock
        mock_ai = MagicMock()
        mock_ai._client.models.generate_content = MagicMock(return_value=mock_resp)
        mock_get_ai.return_value = mock_ai

        # Setup Supabase storage mock
        mock_storage_class.from_env.return_value = mock_storage_client

        # Call the function
        result = await generate_product_packshot(
            shop_name=shop_name,
            item_name=item_name
        )

        # Verify Gemini was called with correct prompt
        mock_ai._client.models.generate_content.assert_called_once()
        call_args = mock_ai._client.models.generate_content.call_args
        assert call_args[1]["model"] == "gemini-2.5-flash-image"
        contents = call_args[1]["contents"]
        assert len(contents) == 1
        assert shop_name in contents[0]["text"]
        assert item_name in contents[0]["text"]
        assert "white background" in contents[0]["text"].lower()

        # Verify image was uploaded to Supabase with correct path
        mock_storage_client.upload_bytes.assert_called_once()
        upload_call = mock_storage_client.upload_bytes.call_args
        assert upload_call.kwargs["image_bytes"] == mock_image_bytes
        assert "generated/Zara" in upload_call.kwargs["folder"]
        assert upload_call.kwargs["content_type"] == "image/png"
        assert upload_call.kwargs["suffix"] == ".png"

        # Verify result
        assert result == "https://supabase.com/bucket/generated/Zara/Blue_T_Shirt-abc12345.png"


@pytest.mark.asyncio
async def test_generate_product_packshot_gemini_failure():
    """Test that function raises error when Gemini fails."""
    shop_name = "Lululemon"
    item_name = "Flow Y Bra"

    with patch("app.services.product_image_fallback.get_ai_provider") as mock_get_ai:
        # Setup AI provider to raise exception
        mock_ai = MagicMock()
        mock_ai._client.models.generate_content.side_effect = Exception("Gemini API error")
        mock_get_ai.return_value = mock_ai

        # Call should raise exception
        with pytest.raises(Exception, match="Gemini API error"):
            await generate_product_packshot(
                shop_name=shop_name,
                item_name=item_name
            )


@pytest.mark.asyncio
async def test_generate_product_packshot_timeout():
    """Test that function raises TimeoutError when operation exceeds timeout."""
    shop_name = "Nike"
    item_name = "Air Max"

    with patch("app.services.product_image_fallback.get_ai_provider") as mock_get_ai, \
         patch("asyncio.wait_for") as mock_wait_for:

        # Setup timeout
        mock_wait_for.side_effect = TimeoutError("Operation timed out")

        # Setup AI provider mock
        mock_ai = MagicMock()
        mock_get_ai.return_value = mock_ai

        # Call should raise TimeoutError
        with pytest.raises(TimeoutError):
            await generate_product_packshot(
                shop_name=shop_name,
                item_name=item_name
            )


@pytest.mark.asyncio
async def test_generate_product_packshot_no_image_in_response():
    """Test that function raises ValueError when Gemini returns no image."""
    shop_name = "Adidas"
    item_name = "Running Shoes"

    # Mock Gemini response with no image
    mock_candidate = MagicMock()
    mock_candidate.content.parts = []  # No parts with image
    mock_resp = MagicMock()
    mock_resp.candidates = [mock_candidate]

    with patch("app.services.product_image_fallback.get_ai_provider") as mock_get_ai:
        # Setup AI provider mock
        mock_ai = MagicMock()
        mock_ai._client.models.generate_content = MagicMock(return_value=mock_resp)
        mock_get_ai.return_value = mock_ai

        # Call should raise ValueError
        with pytest.raises(ValueError, match="Could not extract image bytes"):
            await generate_product_packshot(
                shop_name=shop_name,
                item_name=item_name
            )


@pytest.mark.asyncio
async def test_generate_product_packshot_supabase_upload_failure():
    """Test that function raises error when Supabase upload fails."""
    shop_name = "H&M"
    item_name = "Jeans"

    # Mock image bytes from Gemini
    mock_image_bytes = b"fake_image_data"

    # Mock Gemini response
    mock_candidate = MagicMock()
    mock_part = MagicMock()
    mock_part.inline_data.data = mock_image_bytes
    mock_candidate.content.parts = [mock_part]
    mock_resp = MagicMock()
    mock_resp.candidates = [mock_candidate]

    # Mock Supabase storage to fail
    mock_storage_client = MagicMock()
    mock_storage_client.upload_bytes.side_effect = Exception("Supabase upload error")

    with patch("app.services.product_image_fallback.get_ai_provider") as mock_get_ai, \
         patch("app.services.product_image_fallback.SupabaseStorageClient") as mock_storage_class:

        # Setup AI provider mock
        mock_ai = MagicMock()
        mock_ai._client.models.generate_content = MagicMock(return_value=mock_resp)
        mock_get_ai.return_value = mock_ai

        # Setup Supabase storage mock
        mock_storage_class.from_env.return_value = mock_storage_client

        # Call should raise exception
        with pytest.raises(Exception, match="Supabase upload error"):
            await generate_product_packshot(
                shop_name=shop_name,
                item_name=item_name
            )
