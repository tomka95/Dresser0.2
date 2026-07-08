"""Today's Look — GET / remix / wear.

Runs on the real SQLite substrate (no live LLM, no network anywhere):
  * weather is inert (no saved location -> forecast_for_facts returns None),
  * calendar is inert (no CalendarAccount -> empty block),
  * the grid collage's download + store seams are monkeypatched so compose_grid
    runs for real (pure PIL) without hitting Supabase.

Covers: auth, cross-user reject, thin-closet starter fallback, deterministic
stability, missing-image placeholder, remix variety + rate limit, wear
persistence + idempotency + learning signals.
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, engine
from app.models import (
    ClothingItem,
    PreferenceSignal,
    SavedOutfit,
    StyleEvent,
    User,
)
from app.services.stylist import collage as collage_mod
from main import app
from tests._authutil import mint_supabase_token


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _stub_collage_io(monkeypatch):
    """Make the grid collage deterministic + offline: a tiny real PNG for every
    download, a fixed URL for every store. compose_grid still runs for real."""
    buf = io.BytesIO()
    Image.new("RGB", (24, 24), (120, 120, 120)).save(buf, format="PNG")
    png = buf.getvalue()
    monkeypatch.setattr(collage_mod, "_download", lambda url: (png, "image/png"))
    monkeypatch.setattr(
        collage_mod, "_store", lambda user_id, data: "https://cdn.test/grid.jpg"
    )
    # A cold cache per test so the store stub is actually exercised.
    collage_mod._cache.clear()


@pytest.fixture
def user1(db: Session):
    u = User(email="tl1@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture
def user2(db: Session):
    u = User(email="tl2@example.com", hashed_password="x")
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


def _item(db, user, name, category, **attrs):
    attrs.setdefault("image_url", f"https://cdn.test/{name}.jpg")
    attrs.setdefault("image_status", "resolved")
    it = ClothingItem(user_id=user.id, name=name, category=category, **attrs)
    db.add(it); db.commit(); db.refresh(it)
    return it


def _full_closet(db, user):
    """A top + bottom + footwear -> a sufficient (complete) outfit."""
    top = _item(db, user, "Linen shirt", "top", formality=3, warmth=2)
    bottom = _item(db, user, "Black jeans", "bottom", formality=3, warmth=2)
    shoes = _item(db, user, "Chelsea boots", "footwear", formality=3, warmth=2)
    return top, bottom, shoes


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def test_get_requires_auth(client):
    r = client.get("/todays-look")
    assert r.status_code in (401, 403)


def test_wear_requires_auth(client):
    r = client.post("/todays-look/wear", json={"itemIds": []})
    assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET — happy path + determinism + collage
# ---------------------------------------------------------------------------
def test_get_composes_a_look(client, db, user1, tok1):
    top, bottom, shoes = _full_closet(db, user1)
    r = client.get("/todays-look", headers=_auth(tok1))
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "look"
    assert set(body["itemIds"]) == {str(top.id), str(bottom.id), str(shoes.id)}
    # Title = item names joined.
    assert "Linen shirt" in body["title"]
    # Pure-white grid collage produced (stubbed store URL).
    assert body["collageUrl"] == "https://cdn.test/grid.jpg"
    # Caption is deterministic + non-empty.
    assert body["caption"]
    # outfit_shown emitted (ids/counts only, no titles).
    ev = (
        db.query(StyleEvent)
        .filter_by(user_id=user1.id, event_type="outfit_shown")
        .one()
    )
    assert ev.properties.get("item_count") == 3
    assert "summary" not in ev.properties  # no event titles anywhere


def test_get_is_deterministic(client, db, user1, tok1):
    _full_closet(db, user1)
    a = client.get("/todays-look", headers=_auth(tok1)).json()
    b = client.get("/todays-look", headers=_auth(tok1)).json()
    assert a["itemIds"] == b["itemIds"]
    assert a["title"] == b["title"]
    assert a["caption"] == b["caption"]


# ---------------------------------------------------------------------------
# Thin closet -> starter fallback (never 500)
# ---------------------------------------------------------------------------
def test_thin_closet_returns_starter(client, db, user1, tok1):
    _item(db, user1, "Lonely tee", "top")  # no bottom, no footwear
    r = client.get("/todays-look", headers=_auth(tok1))
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "starter"
    assert body["note"]


def test_empty_closet_returns_starter(client, db, user1, tok1):
    r = client.get("/todays-look", headers=_auth(tok1))
    assert r.status_code == 200
    assert r.json()["kind"] == "starter"


# ---------------------------------------------------------------------------
# Missing image -> placeholder tile, never skipped, never breaks
# ---------------------------------------------------------------------------
def test_missing_image_still_placed(client, db, user1, tok1):
    _item(db, user1, "Linen shirt", "top")
    _item(db, user1, "Black jeans", "bottom")
    # Footwear present in the outfit but with NO usable image.
    shoes = _item(db, user1, "Mystery shoes", "footwear",
                  image_url=None, image_status="pending")
    r = client.get("/todays-look", headers=_auth(tok1))
    assert r.status_code == 200
    body = r.json()
    # The imageless item is STILL in the outfit (not skipped)...
    assert str(shoes.id) in body["itemIds"]
    by_id = {it["id"]: it for it in body["items"]}
    assert by_id[str(shoes.id)]["hasImage"] is False
    # ...and the collage still renders (other items have real images).
    assert body["collageUrl"] == "https://cdn.test/grid.jpg"


# ---------------------------------------------------------------------------
# Remix — variety + rate limit + reject/shown events
# ---------------------------------------------------------------------------
def test_remix_excludes_current_items(client, db, user1, tok1):
    top, bottom, shoes = _full_closet(db, user1)
    # A second footwear option so remix can vary at least one slot.
    alt = _item(db, user1, "White sneakers", "footwear", formality=2, warmth=2)
    current = [str(top.id), str(bottom.id), str(shoes.id)]
    r = client.post("/todays-look/remix", headers=_auth(tok1),
                    json={"itemIds": current})
    assert r.status_code == 200
    body = r.json()
    # The excluded footwear must not reappear; the alternative should.
    assert str(shoes.id) not in body["itemIds"]
    assert str(alt.id) in body["itemIds"]
    # reject(old) + shown(new) both logged.
    assert db.query(StyleEvent).filter_by(
        user_id=user1.id, event_type="outfit_reject").count() == 1
    assert db.query(StyleEvent).filter_by(
        user_id=user1.id, event_type="outfit_shown").count() == 1


def test_remix_rate_limited(client, db, user1, tok1, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "CHAT_RATE_LIMIT_PER_MINUTE", 2)
    _full_closet(db, user1)
    codes = [
        client.post("/todays-look/remix", headers=_auth(tok1),
                    json={"itemIds": []}).status_code
        for _ in range(4)
    ]
    assert 429 in codes


def test_remix_rejects_foreign_item_ids(client, db, user1, user2, tok2):
    top, bottom, shoes = _full_closet(db, user1)  # belong to user1
    # user2 references user1's items — excludes are validated only as ids here,
    # but the composed result must contain NONE of user1's items (RLS + app filter).
    r = client.post("/todays-look/remix", headers=_auth(tok2),
                    json={"itemIds": [str(top.id)]})
    assert r.status_code == 200
    body = r.json()
    assert str(top.id) not in body["itemIds"]
    assert body["kind"] == "starter"  # user2 has an empty closet


# ---------------------------------------------------------------------------
# Wear — persistence, cross-user reject, idempotency, learning
# ---------------------------------------------------------------------------
def test_wear_persists_worn_outfit(client, db, user1, tok1):
    top, bottom, shoes = _full_closet(db, user1)
    ids = [str(top.id), str(bottom.id), str(shoes.id)]
    r = client.post("/todays-look/wear", headers=_auth(tok1), json={"itemIds": ids})
    assert r.status_code == 201
    body = r.json()
    assert body["ok"] and body["itemCount"] == 3 and body["idempotent"] is False

    saved = db.query(SavedOutfit).filter_by(user_id=user1.id).one()
    assert saved.source == "composer"
    assert saved.status == "worn"
    assert saved.worn_at is not None
    # Events: accept + worn.
    types = {e.event_type for e in db.query(StyleEvent).filter_by(user_id=user1.id)}
    assert {"outfit_accept", "outfit_worn"} <= types
    # Reinforcement signals written + wear telemetry bumped.
    assert db.query(PreferenceSignal).filter_by(
        user_id=user1.id, source="outfit_feedback").count() >= 1
    db.refresh(top)
    assert int(top.wear_count or 0) == 1


def test_wear_is_idempotent_per_day(client, db, user1, tok1):
    top, bottom, shoes = _full_closet(db, user1)
    ids = [str(top.id), str(bottom.id), str(shoes.id)]
    first = client.post("/todays-look/wear", headers=_auth(tok1),
                        json={"itemIds": ids}).json()
    second = client.post("/todays-look/wear", headers=_auth(tok1),
                         json={"itemIds": list(reversed(ids))}).json()
    assert second["idempotent"] is True
    assert second["outfitId"] == first["outfitId"]
    assert db.query(SavedOutfit).filter_by(user_id=user1.id).count() == 1


def test_wear_rejects_foreign_item_ids(client, db, user1, user2, tok2):
    top, bottom, shoes = _full_closet(db, user1)  # belong to user1
    r = client.post("/todays-look/wear", headers=_auth(tok2),
                    json={"itemIds": [str(top.id)]})
    assert r.status_code == 422
    assert db.query(SavedOutfit).filter_by(user_id=user2.id).count() == 0


def test_wear_requires_item_ids(client, db, user1, tok1):
    r = client.post("/todays-look/wear", headers=_auth(tok1), json={"itemIds": []})
    assert r.status_code == 422
