"""Tests for POST /events + server-derived style_events (Wave S0 Branch C)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import SessionLocal, Base, engine
from app.models import User, ClothingItem, StyleEvent
from tests._authutil import mint_supabase_token
from main import app


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def user1(db: Session):
    u = User(email="e1@example.com", hashed_password="x", display_name="U1")
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture
def user2(db: Session):
    u = User(email="e2@example.com", hashed_password="x", display_name="U2")
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture
def tok1(user1):
    return mint_supabase_token(sub=str(user1.id))


@pytest.fixture
def tok2(user2):
    return mint_supabase_token(sub=str(user2.id))


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def _item(db, user, **kw):
    # clothing_items.category is NOT NULL (migration 0030); default it so these
    # event/favorite tests (which don't exercise category) still insert a valid row.
    kw.setdefault("category", "top")
    it = ClothingItem(user_id=user.id, name=kw.pop("name", "Tee"), **kw)
    db.add(it); db.commit(); db.refresh(it)
    return it


# --- auth / spoofing --------------------------------------------------------
def test_events_requires_auth(client):
    assert client.post("/events", json={"events": [{"eventType": "item_view"}]}).status_code == 401


def test_user_id_is_server_set_not_spoofable(client, db, user1, user2, tok1):
    # A body that tries to set user_id to user2 must be ignored (extra=ignore) and
    # the row must belong to the token subject (user1).
    r = client.post(
        "/events",
        headers=_auth(tok1),
        json={"events": [{"eventType": "session_start", "user_id": str(user2.id), "source": "system"}]},
    )
    assert r.status_code == 202
    rows = db.query(StyleEvent).all()
    assert len(rows) == 1
    assert rows[0].user_id == user1.id  # never user2


def test_unknown_event_type_rejected(client, tok1):
    r = client.post("/events", headers=_auth(tok1), json={"events": [{"eventType": "definitely_not_real"}]})
    assert r.status_code == 422


def test_cannot_reference_another_users_item(client, db, user2, tok1):
    victim_item = _item(db, user2)  # belongs to user2
    r = client.post(
        "/events",
        headers=_auth(tok1),
        json={"events": [{"eventType": "item_view", "itemId": str(victim_item.id)}]},
    )
    assert r.status_code == 422  # cross-user item ref rejected


def test_valid_client_event_persists(client, db, user1, tok1):
    it = _item(db, user1)
    r = client.post(
        "/events",
        headers=_auth(tok1),
        json={"events": [
            {"eventType": "item_view", "itemId": str(it.id), "source": "closet_grid"},
            {"eventType": "expand", "itemId": str(it.id), "source": "closet_detail",
             "properties": {"dwell_ms": 1200}},
        ]},
    )
    assert r.status_code == 202
    assert r.json()["accepted"] == 2
    kinds = {e.event_type for e in db.query(StyleEvent).all()}
    assert kinds == {"item_view", "expand"}


def test_batch_cap_enforced(client, tok1):
    from app.core.config import settings
    over = [{"eventType": "impression"} for _ in range(settings.EVENTS_MAX_BATCH + 1)]
    r = client.post("/events", headers=_auth(tok1), json={"events": over})
    assert r.status_code == 422


def test_oversized_properties_are_truncated_not_rejected(client, db, user1, tok1):
    r = client.post(
        "/events",
        headers=_auth(tok1),
        json={"events": [{"eventType": "impression", "properties": {"note": "x" * 5000}}]},
    )
    assert r.status_code == 202
    ev = db.query(StyleEvent).first()
    assert len(ev.properties["note"]) <= 512


# --- server-derived: favorite persistence + event via PATCH -----------------
def test_patch_persists_favorite_and_emits_event(client, db, user1, tok1):
    it = _item(db, user1)
    assert it.is_favorite is False
    r = client.patch(f"/closet/{it.id}", headers=_auth(tok1),
                      json={"isFavorite": True, "eventSource": "closet_grid"})
    assert r.status_code == 200
    assert r.json()["isFavorite"] is True
    db.refresh(it)
    assert it.is_favorite is True
    favs = db.query(StyleEvent).filter(StyleEvent.event_type == "favorite").all()
    assert len(favs) == 1
    assert favs[0].item_id == it.id
    assert favs[0].properties["value"] is True
    assert favs[0].source == "closet_grid"


def test_patch_edit_emits_edit_field(client, db, user1, tok1):
    it = _item(db, user1, brand="Old")
    r = client.patch(f"/closet/{it.id}", headers=_auth(tok1), json={"brand": "New", "color": "blue"})
    assert r.status_code == 200
    fields = {e.properties.get("field") for e in
              db.query(StyleEvent).filter(StyleEvent.event_type == "edit_field").all()}
    assert {"brand", "color"} <= fields


def test_favorite_noop_when_unchanged(client, db, user1, tok1):
    it = _item(db, user1)
    # setting False on an already-False item should not emit a favorite event
    r = client.patch(f"/closet/{it.id}", headers=_auth(tok1), json={"isFavorite": False})
    assert r.status_code == 200
    assert db.query(StyleEvent).filter(StyleEvent.event_type == "favorite").count() == 0
