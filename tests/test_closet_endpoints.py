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


def test_post_closet_stages_manual_candidate(
    client: TestClient,
    db: Session,
    test_user1: User,
    user1_token: str,
    monkeypatch,
):
    """Photo-seam Phase 4: POST /closet no longer inserts an item — it stages a
    source_type='manual' candidate + run and returns 202; the item is born through
    the confirm chokepoint once the shared seam produces its verified card."""
    import app.photo_closet.generation_service as gen
    from app.models import IngestCandidate, IngestRun

    monkeypatch.setattr(gen, "generation_armed", lambda: True)
    monkeypatch.setattr(gen, "_storage_from_env", lambda: object())
    monkeypatch.setattr(gen, "manual_generate_background", lambda *a: None)

    payload = {
        "name": "New Test Item",
        "category": "top",
        "brand": "Test Brand",
        "color": "blue",
        # Not our storage -> ignored as a generation reference (SSRF guard).
        "imageUrl": "https://example.com/image.jpg",
    }
    response = client.post(
        "/closet", json=payload, headers={"Authorization": f"Bearer {user1_token}"}
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "tailoring"

    # NO clothing_item exists yet — birth happens only at the confirm chokepoint.
    assert db.query(ClothingItem).filter(
        ClothingItem.user_id == test_user1.id, ClothingItem.name == "New Test Item"
    ).first() is None

    cand = db.query(IngestCandidate).filter(
        IngestCandidate.id == body["candidateId"]
    ).one()
    assert cand.source_type == "manual" and cand.pipeline_state == "staged"
    assert cand.name == "New Test Item" and cand.brand == "Test Brand"
    assert cand.image_url is None            # foreign URL never fetched as a reference
    run = db.query(IngestRun).filter(IngestRun.sync_id == body["syncId"]).one()
    assert run.source_type == "manual" and run.status == "running"


def test_post_closet_refused_when_generation_unavailable(
    client: TestClient,
    db: Session,
    test_user1: User,
    user1_token: str,
    monkeypatch,
):
    """Without the generation seam a compliant card can never be produced — the add
    is refused rather than creating an invariant-violating (imageless) item."""
    import app.photo_closet.generation_service as gen

    monkeypatch.setattr(gen, "generation_armed", lambda: False)
    response = client.post(
        "/closet", json={"name": "Created Item", "category": "outerwear"},
        headers={"Authorization": f"Bearer {user1_token}"},
    )
    assert response.status_code == 503
    assert db.query(ClothingItem).filter(
        ClothingItem.user_id == test_user1.id
    ).count() == 0


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

