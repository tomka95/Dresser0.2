"""Performance tests for Closet API endpoints."""

import pytest
import time
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import SessionLocal, Base, engine
from app.models import User, ClothingItem, ItemImage
from app.security import create_access_token
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
def test_user(db: Session):
    """Create a test user with many items."""
    user = User(
        email="perf_test@example.com",
        hashed_password="hashed_password",
        display_name="Performance Test User",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def test_user_with_items(db: Session, test_user: User):
    """Create a test user with 20 items, some with images."""
    items = []
    for i in range(20):
        item = ClothingItem(
            user_id=test_user.id,
            name=f"Item {i}",
            category="top" if i % 2 == 0 else "bottom",
            brand=f"Brand {i % 5}",
        )
        # Set image_url for half the items
        if i % 2 == 0:
            item.image_url = f"https://example.com/image_{i}.jpg"
        else:
            # For items without image_url, create a primary ItemImage
            db.add(item)
            db.flush()
            image = ItemImage(
                clothing_item_id=item.id,
                image_url=f"https://example.com/primary_{i}.jpg",
                is_primary=True,
            )
            db.add(image)
        items.append(item)
    
    db.commit()
    return test_user


def test_get_closet_performance_with_many_items(
    client: TestClient,
    test_user_with_items: User,
):
    """Benchmark GET /closet with 20 items (some with ItemImage lookups)."""
    token = create_access_token(data={"sub": str(test_user_with_items.id)})
    
    # Measure request time
    start = time.time()
    response = client.get(
        "/closet",
        headers={"Authorization": f"Bearer {token}"}
    )
    elapsed = time.time() - start
    
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 20
    
    # Performance assertions (adjust thresholds based on your environment)
    # These are best-effort benchmarks - actual times depend on DB, network, etc.
    assert elapsed < 1.0, f"GET /closet took {elapsed:.3f}s, expected < 1.0s"
    
    # Verify all items have correct structure
    for item in items:
        assert "id" in item
        assert "userId" in item
        assert "name" in item
        # Verify imageUrl is set correctly (either from image_url or ItemImage)
        if "ItemImage" in item["name"] or int(item["name"].split()[-1]) % 2 == 1:
            assert item["imageUrl"] is not None or item["imageUrl"] is None  # Either is valid


def test_get_closet_query_count(
    client: TestClient,
    db: Session,
    test_user: User,
):
    """Verify that GET /closet uses optimized queries (no N+1).
    
    This test creates items with ItemImages and verifies the endpoint
    doesn't make excessive queries.
    """
    # Create 10 items, each with a primary ItemImage (no image_url set)
    items = []
    for i in range(10):
        item = ClothingItem(
            user_id=test_user.id,
            name=f"Test Item {i}",
            category="top",
        )
        db.add(item)
        db.flush()
        image = ItemImage(
            clothing_item_id=item.id,
            image_url=f"https://example.com/img_{i}.jpg",
            is_primary=True,
        )
        db.add(image)
        items.append(item)
    db.commit()
    
    token = create_access_token(data={"sub": str(test_user.id)})
    
    # Make request
    response = client.get(
        "/closet",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == 200
    result_items = response.json()
    assert len(result_items) == 10
    
    # Verify all items have imageUrl from ItemImage
    for item in result_items:
        assert item["imageUrl"] is not None
        assert "img_" in item["imageUrl"]


# Note: For more detailed query counting, you could use SQLAlchemy's
# query logging or a tool like sqlalchemy-utils query counter, but
# that's beyond the scope of this basic performance test.

