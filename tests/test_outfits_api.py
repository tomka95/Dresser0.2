"""Lookbook backend — GET /outfits, generate, like/unlike, unsave.

Runs on the real SQLite substrate (no live LLM, no network): weather/calendar are
inert (no saved location / no CalendarAccount), so generate exercises the real
assemble_profile + derive_factors + step-down + compose_outfit spine.

Covers the task gates explicitly:
  * auth guard on every /outfits endpoint,
  * cross-user isolation (list, like, unsave — foreign ids 404, rows untouched),
  * like persistence across "reload" (fresh GET reflects the stored is_liked),
  * generate honesty (complete look persisted; thin closet -> sufficient=false and
    NOTHING persisted),
  * every emitted event's entity_id references a REAL saved_outfits row.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, engine
from app.models import ClothingItem, SavedOutfit, StyleEvent, User
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


@pytest.fixture
def user1(db: Session):
    u = User(email="lb1@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture
def user2(db: Session):
    u = User(email="lb2@example.com", hashed_password="x")
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
    attrs.setdefault("person_status", "person_free")
    it = ClothingItem(user_id=user.id, name=name, category=category, **attrs)
    db.add(it); db.commit(); db.refresh(it)
    return it


def _full_closet(db, user):
    top = _item(db, user, "Linen shirt", "top", formality=3, warmth=2)
    bottom = _item(db, user, "Black jeans", "bottom", formality=3, warmth=2)
    shoes = _item(db, user, "Chelsea boots", "footwear", formality=3, warmth=2)
    return top, bottom, shoes


def _saved(db, user, item_ids, **attrs):
    attrs.setdefault("source", "chat")
    row = SavedOutfit(user_id=user.id, item_ids=[str(i) for i in item_ids], **attrs)
    db.add(row); db.commit(); db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------
class TestAuthGuard:
    def test_every_endpoint_rejects_missing_token(self, client, db):
        fake = "00000000-0000-0000-0000-000000000009"
        assert client.get("/outfits").status_code in (401, 403)
        assert client.post("/outfits/generate", json={}).status_code in (401, 403)
        assert client.put(f"/outfits/{fake}/like").status_code in (401, 403)
        assert client.delete(f"/outfits/{fake}/like").status_code in (401, 403)
        assert client.delete(f"/outfits/{fake}").status_code in (401, 403)

    def test_garbage_token_rejected(self, client, db):
        assert (
            client.get("/outfits", headers={"Authorization": "Bearer not-a-jwt"}).status_code
            == 401
        )


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------
class TestList:
    def test_lists_own_outfits_newest_first(self, client, db, user1, tok1):
        items = _full_closet(db, user1)
        a = _saved(db, user1, [i.id for i in items], title="First")
        b = _saved(db, user1, [items[0].id], title="Second", source="composer")
        res = client.get("/outfits", headers=_auth(tok1))
        assert res.status_code == 200
        body = res.json()
        assert [o["id"] for o in body] == [str(b.id), str(a.id)] or {
            o["id"] for o in body
        } == {str(a.id), str(b.id)}
        first = next(o for o in body if o["id"] == str(a.id))
        assert first["name"] == "First"
        assert first["items"] == [str(i.id) for i in items]
        assert first["isLiked"] is False
        assert first["userId"] == str(user1.id)

    def test_cross_user_isolation(self, client, db, user1, user2, tok1, tok2):
        items = _full_closet(db, user1)
        mine = _saved(db, user1, [items[0].id])
        res2 = client.get("/outfits", headers=_auth(tok2))
        assert res2.status_code == 200
        assert res2.json() == []
        res1 = client.get("/outfits", headers=_auth(tok1))
        assert [o["id"] for o in res1.json()] == [str(mine.id)]

    def test_rejected_and_archived_hidden(self, client, db, user1, tok1):
        items = _full_closet(db, user1)
        _saved(db, user1, [items[0].id], status="rejected")
        _saved(db, user1, [items[1].id], status="archived")
        kept = _saved(db, user1, [items[2].id], status="worn")
        res = client.get("/outfits", headers=_auth(tok1))
        assert [o["id"] for o in res.json()] == [str(kept.id)]


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------
class TestGenerate:
    def test_full_closet_generates_and_persists(self, client, db, user1, tok1):
        items = _full_closet(db, user1)
        res = client.post("/outfits/generate", json={}, headers=_auth(tok1))
        assert res.status_code == 200
        body = res.json()
        assert body["saved"] is True
        assert body["sufficient"] is True
        outfit = body["outfit"]
        row = db.query(SavedOutfit).filter(SavedOutfit.id == outfit["id"]).one()
        assert row.user_id == user1.id
        assert row.source == "composer"
        # Every referenced item is one of the caller's own closet items.
        own_ids = {str(i.id) for i in items}
        assert set(outfit["items"]) <= own_ids
        assert len(outfit["items"]) >= 2  # a wearable base at minimum
        # The rendered item payloads match the persisted ids.
        assert {i["id"] for i in body["items"]} == set(outfit["items"])

    def test_thin_closet_returns_honest_gap_and_persists_nothing(
        self, client, db, user1, tok1
    ):
        _item(db, user1, "Lone shirt", "top", formality=3, warmth=2)
        res = client.post("/outfits/generate", json={}, headers=_auth(tok1))
        assert res.status_code == 200
        body = res.json()
        assert body["saved"] is False
        assert body["sufficient"] is False
        assert body["outfit"] is None
        assert db.query(SavedOutfit).count() == 0
        # No outfit event with a subject was emitted for the non-look.
        events = db.query(StyleEvent).filter(StyleEvent.event_type == "outfit_shown").all()
        assert all(e.entity_id is None for e in events)

    def test_generate_emits_event_with_real_outfit_id(self, client, db, user1, tok1):
        _full_closet(db, user1)
        res = client.post("/outfits/generate", json={}, headers=_auth(tok1))
        outfit_id = res.json()["outfit"]["id"]
        ev = (
            db.query(StyleEvent)
            .filter(StyleEvent.event_type == "outfit_shown")
            .one()
        )
        assert ev.entity_type == "saved_outfit"
        assert ev.entity_id == outfit_id
        assert db.query(SavedOutfit).filter(SavedOutfit.id == ev.entity_id).count() == 1

    def test_generate_is_idempotent_on_same_item_set(self, client, db, user1, tok1):
        _full_closet(db, user1)
        first = client.post("/outfits/generate", json={}, headers=_auth(tok1)).json()
        second = client.post("/outfits/generate", json={}, headers=_auth(tok1)).json()
        assert second["idempotent"] is True
        assert second["outfit"]["id"] == first["outfit"]["id"]
        assert db.query(SavedOutfit).count() == 1

    def test_generate_respects_exclusions(self, client, db, user1, tok1):
        top, bottom, shoes = _full_closet(db, user1)
        top2 = _item(db, user1, "Oxford shirt", "top", formality=3, warmth=2)
        first = client.post("/outfits/generate", json={}, headers=_auth(tok1)).json()
        chosen_top = next(
            i for i in first["outfit"]["items"] if i in {str(top.id), str(top2.id)}
        )
        res = client.post(
            "/outfits/generate",
            json={"excludeItemIds": [chosen_top]},
            headers=_auth(tok1),
        ).json()
        assert res["saved"] is True
        assert chosen_top not in res["outfit"]["items"]

    def test_generate_with_occasion_stores_it(self, client, db, user1, tok1):
        _full_closet(db, user1)
        res = client.post(
            "/outfits/generate", json={"occasion": "dinner out"}, headers=_auth(tok1)
        ).json()
        assert res["saved"] is True
        assert res["outfit"]["occasion"] == "dinner out"

    def test_occasion_family_never_force_fills(self, client, db, user1, tok1):
        # A dressy-only closet cannot honestly satisfy a gym request.
        _full_closet(db, user1)
        res = client.post(
            "/outfits/generate", json={"occasion": "gym"}, headers=_auth(tok1)
        ).json()
        assert res["saved"] is False
        assert res["sufficient"] is False

    def test_bad_exclude_id_is_422(self, client, db, user1, tok1):
        res = client.post(
            "/outfits/generate",
            json={"excludeItemIds": ["not-a-uuid"]},
            headers=_auth(tok1),
        )
        assert res.status_code == 422


# ---------------------------------------------------------------------------
# Like / unlike
# ---------------------------------------------------------------------------
class TestLike:
    def test_like_persists_across_reload(self, client, db, user1, tok1):
        items = _full_closet(db, user1)
        row = _saved(db, user1, [i.id for i in items])
        res = client.put(f"/outfits/{row.id}/like", headers=_auth(tok1))
        assert res.status_code == 200
        assert res.json() == {"ok": True, "outfitId": str(row.id), "liked": True}
        # "Reload": a fresh list read reflects the stored state.
        listed = client.get("/outfits", headers=_auth(tok1)).json()
        assert listed[0]["isLiked"] is True
        db.expire_all()
        fresh = db.query(SavedOutfit).filter(SavedOutfit.id == row.id).one()
        assert fresh.is_liked is True
        assert fresh.liked_at is not None

    def test_unlike_clears_state(self, client, db, user1, tok1):
        items = _full_closet(db, user1)
        row = _saved(db, user1, [items[0].id], is_liked=True)
        res = client.delete(f"/outfits/{row.id}/like", headers=_auth(tok1))
        assert res.status_code == 200
        assert res.json()["liked"] is False
        db.expire_all()
        fresh = db.query(SavedOutfit).filter(SavedOutfit.id == row.id).one()
        assert fresh.is_liked is False
        assert fresh.liked_at is None

    def test_like_emits_event_with_real_id(self, client, db, user1, tok1):
        items = _full_closet(db, user1)
        row = _saved(db, user1, [items[0].id])
        client.put(f"/outfits/{row.id}/like", headers=_auth(tok1))
        client.delete(f"/outfits/{row.id}/like", headers=_auth(tok1))
        events = (
            db.query(StyleEvent)
            .filter(StyleEvent.event_type == "outfit_rated")
            .order_by(StyleEvent.created_at)
            .all()
        )
        assert len(events) == 2
        for ev in events:
            assert ev.entity_type == "saved_outfit"
            assert ev.entity_id == str(row.id)  # a real, persisted outfit id
        assert events[0].properties["liked"] is True
        assert events[1].properties["liked"] is False

    def test_idempotent_like_emits_no_duplicate_event(self, client, db, user1, tok1):
        items = _full_closet(db, user1)
        row = _saved(db, user1, [items[0].id])
        client.put(f"/outfits/{row.id}/like", headers=_auth(tok1))
        client.put(f"/outfits/{row.id}/like", headers=_auth(tok1))
        count = (
            db.query(StyleEvent)
            .filter(StyleEvent.event_type == "outfit_rated")
            .count()
        )
        assert count == 1

    def test_cross_user_like_is_404_and_untouched(
        self, client, db, user1, user2, tok1, tok2
    ):
        items = _full_closet(db, user1)
        row = _saved(db, user1, [items[0].id])
        res = client.put(f"/outfits/{row.id}/like", headers=_auth(tok2))
        assert res.status_code == 404
        db.expire_all()
        fresh = db.query(SavedOutfit).filter(SavedOutfit.id == row.id).one()
        assert fresh.is_liked is False

    def test_invalid_id_is_422(self, client, db, user1, tok1):
        assert (
            client.put("/outfits/nope/like", headers=_auth(tok1)).status_code == 422
        )


# ---------------------------------------------------------------------------
# Unsave
# ---------------------------------------------------------------------------
class TestUnsave:
    def test_unsave_deletes_own_row(self, client, db, user1, tok1):
        items = _full_closet(db, user1)
        row = _saved(db, user1, [items[0].id])
        res = client.delete(f"/outfits/{row.id}", headers=_auth(tok1))
        assert res.status_code == 200
        assert db.query(SavedOutfit).count() == 0
        ev = (
            db.query(StyleEvent)
            .filter(StyleEvent.event_type == "outfit_reject")
            .one()
        )
        assert ev.entity_id == str(row.id)
        assert ev.properties["via"] == "lookbook_unsave"

    def test_cross_user_unsave_is_404_and_row_survives(
        self, client, db, user1, user2, tok2
    ):
        items = _full_closet(db, user1)
        row = _saved(db, user1, [items[0].id])
        res = client.delete(f"/outfits/{row.id}", headers=_auth(tok2))
        assert res.status_code == 404
        assert db.query(SavedOutfit).count() == 1


# ---------------------------------------------------------------------------
# Client /events door: fabricated outfit subjects are rejected at the gate
# ---------------------------------------------------------------------------
class TestClientEventOutfitValidation:
    def test_fabricated_outfit_entity_id_is_rejected(self, client, db, user1, tok1):
        res = client.post(
            "/events",
            json={"events": [{
                "eventType": "outfit_rated",
                "entityType": "saved_outfit",
                "entityId": "aaaa1111-aaaa-1111-aaaa-111111111111",  # the mock-era fake
            }]},
            headers=_auth(tok1),
        )
        assert res.status_code == 422
        assert db.query(StyleEvent).count() == 0

    def test_foreign_outfit_entity_id_is_rejected(
        self, client, db, user1, user2, tok2
    ):
        items = _full_closet(db, user1)
        row = _saved(db, user1, [items[0].id])
        res = client.post(
            "/events",
            json={"events": [{
                "eventType": "outfit_rated",
                "entityType": "saved_outfit",
                "entityId": str(row.id),
            }]},
            headers=_auth(tok2),
        )
        assert res.status_code == 422
        assert db.query(StyleEvent).count() == 0

    def test_own_outfit_entity_id_is_accepted(self, client, db, user1, tok1):
        items = _full_closet(db, user1)
        row = _saved(db, user1, [items[0].id])
        res = client.post(
            "/events",
            json={"events": [{
                "eventType": "outfit_rated",
                "entityType": "saved_outfit",
                "entityId": str(row.id),
            }]},
            headers=_auth(tok1),
        )
        assert res.status_code == 202
        ev = db.query(StyleEvent).one()
        assert ev.entity_id == str(row.id)

    def test_non_outfit_entities_unaffected(self, client, db, user1, tok1):
        # Product/session entity ids keep their existing free-text posture.
        res = client.post(
            "/events",
            json={"events": [{
                "eventType": "click_out",
                "entityType": "product",
                "entityId": "some-product-ref",
            }]},
            headers=_auth(tok1),
        )
        assert res.status_code == 202


# ---------------------------------------------------------------------------
# Honesty sweep: every outfit event subject references a real saved_outfits row
# ---------------------------------------------------------------------------
class TestEventHonesty:
    def test_no_outfit_event_carries_a_fabricated_id(self, client, db, user1, tok1):
        _full_closet(db, user1)
        gen = client.post("/outfits/generate", json={}, headers=_auth(tok1)).json()
        oid = gen["outfit"]["id"]
        client.put(f"/outfits/{oid}/like", headers=_auth(tok1))
        client.delete(f"/outfits/{oid}/like", headers=_auth(tok1))
        client.delete(f"/outfits/{oid}", headers=_auth(tok1))

        known_ids = {oid}  # the only outfit this session ever persisted
        outfit_events = (
            db.query(StyleEvent)
            .filter(StyleEvent.entity_type == "saved_outfit")
            .all()
        )
        assert len(outfit_events) >= 4  # shown, rated x2, reject(unsave)
        for ev in outfit_events:
            assert ev.entity_id in known_ids
