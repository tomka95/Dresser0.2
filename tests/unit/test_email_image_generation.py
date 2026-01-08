"""Unit tests for email item image generation."""

import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services.ai_image_service import generate_white_bg_product_image_from_text
from app.gmail_closet.models import Item
from app.gmail_closet.email_clothing_service import save_email_items_for_user


@pytest.mark.asyncio
async def test_generate_white_bg_product_image_from_text_success():
    """Test successful image generation and upload."""
    user_id = uuid4()
    brand = "Lululemon"
    product_name = "Flow Y Bra Nulu Light Support"
    
    # Mock image bytes returned by the AI provider helper
    mock_image_bytes = b"fake_image_data"
    
    # Mock Supabase storage
    mock_storage_client = MagicMock()
    mock_storage_client.upload_bytes.return_value = "https://supabase.com/bucket/email_items/user/image.png"
    
    with patch("app.services.openai_image_service._generate_image_from_text_prompt") as mock_generate_image, \
         patch("app.services.openai_image_service.SupabaseStorageClient") as mock_storage_class:
        
        # Setup image generation mock to return raw bytes
        mock_generate_image.return_value = mock_image_bytes
        
        # Setup Supabase storage mock
        mock_storage_class.from_env.return_value = mock_storage_client
        
        # Call the function
        result = await generate_white_bg_product_image_from_text(
            brand=brand,
            product_name=product_name,
            user_id=user_id,
        )
        
        # Verify image generation helper was called
        mock_generate_image.assert_called_once()
        call_args = mock_generate_image.call_args
        prompt = call_args[0][0]  # First positional argument is the prompt
        assert brand in prompt
        assert product_name in prompt
        assert "white background" in prompt.lower()
        
        # Verify image was uploaded to Supabase
        mock_storage_client.upload_bytes.assert_called_once()
        upload_call = mock_storage_client.upload_bytes.call_args
        assert upload_call.kwargs["image_bytes"] == mock_image_bytes
        assert f"email_items/{user_id}" in upload_call.kwargs["folder"]
        
        # Verify result
        assert result == "https://supabase.com/bucket/email_items/user/image.png"


@pytest.mark.asyncio
async def test_generate_white_bg_product_image_from_text_ai_failure():
    """Test that function returns None when AI provider fails."""
    user_id = uuid4()
    brand = "Zara"
    product_name = "Basic T-Shirt"
    
    with patch("app.services.openai_image_service._generate_image_from_text_prompt") as mock_generate_image:
        mock_generate_image.side_effect = Exception("AI provider error")
        
        result = await generate_white_bg_product_image_from_text(
            brand=brand,
            product_name=product_name,
            user_id=user_id,
        )
        
        assert result is None


@pytest.mark.asyncio
async def test_generate_white_bg_product_image_from_text_no_image_bytes():
    """Test that function returns None when AI provider returns no image bytes."""
    user_id = uuid4()
    brand = "Adidas"
    product_name = "Running Shoes"
    
    with patch("app.services.openai_image_service._generate_image_from_text_prompt") as mock_generate_image:
        # Mock returning None or empty bytes
        mock_generate_image.return_value = None
        
        result = await generate_white_bg_product_image_from_text(
            brand=brand,
            product_name=product_name,
            user_id=user_id,
        )
        
        assert result is None


@pytest.mark.asyncio
async def test_generate_white_bg_product_image_from_text_upload_failure():
    """Test that function returns None when Supabase upload fails."""
    user_id = uuid4()
    brand = "Nike"
    product_name = "Air Max Sneakers"
    
    # Mock image bytes returned by the AI provider helper
    mock_image_bytes = b"fake_image_data"
    
    # Mock Supabase storage to fail
    mock_storage_client = MagicMock()
    mock_storage_client.upload_bytes.side_effect = Exception("Supabase upload error")
    
    with patch("app.services.openai_image_service._generate_image_from_text_prompt") as mock_generate_image, \
         patch("app.services.openai_image_service.SupabaseStorageClient") as mock_storage_class:
        
        # Setup image generation mock to return raw bytes
        mock_generate_image.return_value = mock_image_bytes
        
        # Setup Supabase storage mock
        mock_storage_class.from_env.return_value = mock_storage_client
        
        # Call the function
        result = await generate_white_bg_product_image_from_text(
            brand=brand,
            product_name=product_name,
            user_id=user_id,
        )
        
        # Should return None on failure
        assert result is None


@pytest.mark.asyncio
async def test_save_email_items_for_user_with_images_url():
    """Test that images_url is properly saved when provided in Item."""
    from sqlalchemy.orm import Session
    from unittest.mock import MagicMock
    from uuid import uuid4
    
    user_id = uuid4()
    
    # Create a mock database session
    mock_db = MagicMock(spec=Session)
    mock_db.query.return_value.filter.return_value.first.return_value = None  # No existing item
    mock_db.add = MagicMock()
    mock_db.flush = MagicMock()
    mock_db.commit = MagicMock()
    mock_db.refresh = MagicMock()
    
    # Create an Item with images_url
    item = Item(
        name="Test Product",
        store="Test Brand",
        price=29.99,
        images_url="https://supabase.com/bucket/email_items/user/image.png",
    )
    
    # Call save function (now async)
    result = await save_email_items_for_user(
        db=mock_db,
        user_id=user_id,
        items=[item],
    )
    
    # Verify ClothingItem was created with images_url
    assert len(result) == 1
    assert result[0].images_url == "https://supabase.com/bucket/email_items/user/image.png"
    mock_db.add.assert_called()
    mock_db.commit.assert_called_once()


