"""Tests for Closet API endpoints."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import SessionLocal, Base, engine
from app.models import User, ClothingItem
from tests._authutil import mint_supabase_token
from main import app


@pytest.fixture
def db():
    """Create a test database session."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def test_user1(db: Session):
    """Create a test user."""
    user = User(
        email="test1@example.com",
        hashed_password="hashed_password",
        display_name="Test User 1",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def test_user2(db: Session):
    """Create a second test user."""
    user = User(
        email="test2@example.com",
        hashed_password="hashed_password",
        display_name="Test User 2",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def user1_token(test_user1: User):
    """Create a JWT token for test_user1."""
    return mint_supabase_token(sub=str(test_user1.id))


@pytest.fixture
def user2_token(test_user2: User):
    """Create a JWT token for test_user2."""
    return mint_supabase_token(sub=str(test_user2.id))


def test_get_closet_requires_auth(client: TestClient):
    """Test that GET /closet returns 401 without token."""
    response = client.get("/closet")
    assert response.status_code == 401
    assert "detail" in response.json()


def test_get_closet_returns_only_user_items(
    client: TestClient,
    db: Session,
    test_user1: User,
    test_user2: User,
    user1_token: str,
):
    """Test that GET /closet returns only items for the authenticated user."""
    # Create 3 items for user1
    item1 = ClothingItem(
        user_id=test_user1.id,
        name="User1 Item 1",
        category="top",
        brand="Brand1",
    )
    item2 = ClothingItem(
        user_id=test_user1.id,
        name="User1 Item 2",
        category="bottom",
    )
    item3 = ClothingItem(
        user_id=test_user1.id,
        name="User1 Item 3",
        category="shoes",
    )
    
    # Create 2 items for user2
    item4 = ClothingItem(
        user_id=test_user2.id,
        name="User2 Item 1",
        category="top",
    )
    item5 = ClothingItem(
        user_id=test_user2.id,
        name="User2 Item 2",
        category="dress",
    )
    
    db.add_all([item1, item2, item3, item4, item5])
    db.commit()
    
    # Request items as user1
    response = client.get(
        "/closet",
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    
    assert response.status_code == 200
    items = response.json()
    
    # Should only see user1's items
    assert len(items) == 3
    item_names = [item["name"] for item in items]
    assert "User1 Item 1" in item_names
    assert "User1 Item 2" in item_names
    assert "User1 Item 3" in item_names
    assert "User2 Item 1" not in item_names
    assert "User2 Item 2" not in item_names
    
    # Verify response structure matches ClosetItem contract (camelCase)
    first_item = items[0]
    assert "id" in first_item
    assert "userId" in first_item  # camelCase
    assert "user_id" not in first_item  # no snake_case
    assert "name" in first_item
    assert "category" in first_item
    assert "brand" in first_item
    assert "color" in first_item
    assert "imageUrl" in first_item  # camelCase
    assert "image_url" not in first_item  # no snake_case
    assert "createdAt" in first_item  # camelCase
    assert "created_at" not in first_item  # no snake_case
    assert "updatedAt" in first_item  # camelCase
    assert "updated_at" not in first_item  # no snake_case


def test_post_closet_creates_item(
    client: TestClient,
    db: Session,
    test_user1: User,
    user1_token: str,
):
    """Test that POST /closet creates item and returns camelCase response."""
    payload = {
        "name": "New Test Item",
        "category": "top",
        "brand": "Test Brand",
        "color": "blue",
        "imageUrl": "https://example.com/image.jpg",
    }
    
    response = client.post(
        "/closet",
        json=payload,
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    
    assert response.status_code == 201
    item = response.json()
    
    # Verify response structure (camelCase)
    assert item["name"] == "New Test Item"
    assert item["category"] == "top"
    assert item["brand"] == "Test Brand"
    assert item["color"] == "blue"
    assert item["imageUrl"] == "https://example.com/image.jpg"
    assert item["userId"] == str(test_user1.id)  # camelCase
    assert "id" in item
    assert "createdAt" in item  # camelCase
    assert "updatedAt" in item  # camelCase
    
    # Verify no snake_case fields
    assert "user_id" not in item
    assert "image_url" not in item
    assert "created_at" not in item
    assert "updated_at" not in item
    
    # Verify item was created in database
    db_item = db.query(ClothingItem).filter(ClothingItem.id == item["id"]).first()
    assert db_item is not None
    assert db_item.name == "New Test Item"
    assert db_item.user_id == test_user1.id


def test_post_then_get_includes_item(
    client: TestClient,
    db: Session,
    test_user1: User,
    user1_token: str,
):
    """Test that POST then GET includes the created item."""
    # Create item via POST
    payload = {
        "name": "Created Item",
        "category": "outerwear",
    }
    
    post_response = client.post(
        "/closet",
        json=payload,
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    
    assert post_response.status_code == 201
    created_item = post_response.json()
    created_id = created_item["id"]
    
    # Get items via GET
    get_response = client.get(
        "/closet",
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    
    assert get_response.status_code == 200
    items = get_response.json()
    
    # Verify created item is in the list
    item_ids = [item["id"] for item in items]
    assert created_id in item_ids
    
    # Find the created item in the list
    found_item = next(item for item in items if item["id"] == created_id)
    assert found_item["name"] == "Created Item"
    assert found_item["category"] == "outerwear"


def test_post_closet_validates_category_enum(
    client: TestClient,
    test_user1: User,
    user1_token: str,
):
    """Test that POST /closet validates category against enum."""
    payload = {
        "name": "Invalid Category Item",
        "category": "invalid_category",  # Not in enum
    }
    
    response = client.post(
        "/closet",
        json=payload,
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    
    assert response.status_code == 422  # Validation error


def test_post_closet_requires_name(
    client: TestClient,
    test_user1: User,
    user1_token: str,
):
    """Test that POST /closet requires name field."""
    payload = {
        "category": "top",
    }
    
    response = client.post(
        "/closet",
        json=payload,
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    
    assert response.status_code == 422  # Validation error

