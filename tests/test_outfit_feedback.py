"""Wave S3 outfit feedback -> learning: credit assignment + endpoint + precedence.

Two layers, both on the real SQLite substrate (no live LLM anywhere on this path):

  * credit module (app/services/stylist/outfit_feedback) — the attribute-level
    fan-out from a reject / modify / worn reaction into per-item preference_signals.
  * POST /outfits/feedback — the routed endpoint (RLS-scoped writes, JWT-derived
    user_id, ownership choke point, saved_outfits status update, no-PII events).

Plus the precedence guarantee against the s3a distill recompute: an
outfit_feedback signal outranks inferred and ranks below explicit.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, engine
from app.models import (
    ClothingItem,
    PreferenceSignal,
    SavedOutfit,
    StyleEvent,
    StylePreference,
    User,
)
from tests._authutil import mint_supabase_token
from app.services.stylist import outfit_feedback as credit
from app.services.stylist.distill import recompute_preferences
from main import app


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
    u = User(email="of1@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture
def user2(db: Session):
    u = User(email="of2@example.com", hashed_password="x")
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


def _item(db, user, **attrs) -> ClothingItem:
    it = ClothingItem(user_id=user.id, name=attrs.pop("name", "Item"), **attrs)
    db.add(it); db.commit(); db.refresh(it)
    return it


def _fb(db, user):
    return (
        db.query(PreferenceSignal)
        .filter_by(user_id=user.id, source="outfit_feedback")
        .all()
    )


# ===========================================================================
# Credit module — attribute-level fan-out
# ===========================================================================
def test_reject_formality_direction_is_one_typed_dislike(db, user1):
    items = [_item(db, user1, color_primary="black", formality=4)]
    sigs = credit.apply_reject(
        db, user1.id, items, reason_chips=["formality"],
        directions={"formality": "too_formal"},
    )
    db.commit()
    assert len(sigs) == 1
    s = sigs[0]
    assert (s.key, s.polarity, s.source, s.signal_type) == (
        "formality", "dislike", "outfit_feedback", "outfit_feedback")
    assert s.value["note"] == "too_formal"
    assert 0.0 < s.weight <= 1.0


def test_reject_color_skips_neutral_and_fans_per_item(db, user1):
    navy = _item(db, user1, color_primary="navy")   # neutral -> no palette taste
    red = _item(db, user1, color_primary="red")
    sigs = credit.apply_reject(db, user1.id, [navy, red], reason_chips=["color"])
    db.commit()
    assert len(sigs) == 1
    assert sigs[0].key == "color" and sigs[0].item_id == red.id
    assert sigs[0].polarity == "dislike"


def test_reject_weather_writes_no_durable_signal(db, user1):
    red = _item(db, user1, color_primary="red")
    sigs = credit.apply_reject(db, user1.id, [red], reason_chips=["weather"])
    db.commit()
    assert sigs == []  # situational appropriateness, not a standing taste


def test_reject_item_specific_credits_that_items_attributes(db, user1):
    target = _item(db, user1, color_primary="green", formality=5,
                   brand="Zegna", material="wool")
    sigs = credit.apply_reject(
        db, user1.id, [target], reason_chips=["item_specific"], item_specific=target)
    db.commit()
    dims = {s.key for s in sigs}
    assert {"color", "formality", "brand", "material"} <= dims
    assert all(s.polarity == "dislike" and s.item_id == target.id for s in sigs)
    # item-specific is more precise than a generic reject -> stronger weight.
    assert all(s.weight >= 0.75 for s in sigs)


def test_modify_swap_is_precise_on_differing_attributes(db, user1):
    # red loafer (cotton) -> blue sneaker (cotton): color + category differ; material same.
    removed = _item(db, user1, color_primary="red", sub_category="loafer", material="cotton")
    repl = _item(db, user1, color_primary="blue", sub_category="sneaker", material="cotton")
    kept = _item(db, user1, color_primary="olive", name="shirt")
    sigs = credit.apply_modify(db, user1.id, removed, repl, kept=[kept])
    db.commit()

    triples = {(s.key, s.polarity, s.item_id) for s in sigs}
    assert ("color", "dislike", removed.id) in triples
    assert ("color", "like", repl.id) in triples
    assert ("category", "dislike", removed.id) in triples
    assert ("category", "like", repl.id) in triples
    # identical material axis says nothing -> no material signal.
    assert not any(s.key == "material" for s in sigs)
    # kept item is mildly reinforced.
    assert ("color", "like", kept.id) in triples
    assert all(s.source == "outfit_feedback" for s in sigs)


def test_modify_neutral_swap_axis_is_silent(db, user1):
    removed = _item(db, user1, color_primary="black", sub_category="loafer")
    repl = _item(db, user1, color_primary="white", sub_category="loafer")  # neutral<->neutral, same cat
    sigs = credit.apply_modify(db, user1.id, removed, repl)
    db.commit()
    # both colors neutral AND category identical -> nothing learned.
    assert sigs == []


def test_reinforce_likes_each_items_salient_attributes(db, user1):
    it = _item(db, user1, color_primary="olive", formality=3, brand="Uniqlo")
    sigs = credit.apply_reinforce(db, user1.id, [it])
    db.commit()
    assert {s.key for s in sigs} >= {"color", "formality", "brand"}
    assert all(s.polarity == "like" and s.source == "outfit_feedback" for s in sigs)


# ===========================================================================
# POST /outfits/feedback
# ===========================================================================
def test_feedback_requires_auth(client):
    assert client.post("/outfits/feedback", json={"feedback": "worn"}).status_code == 401


def test_body_cannot_spoof_user_id(client, tok1):
    # extra='forbid' -> a user_id in the body is a 422, never honored.
    r = client.post("/outfits/feedback", headers=_auth(tok1),
                    json={"feedback": "worn", "user_id": "x"})
    assert r.status_code == 422


def test_reject_endpoint_persists_signals_and_event(client, db, user1, tok1):
    red = _item(db, user1, color_primary="red", formality=4)
    r = client.post("/outfits/feedback", headers=_auth(tok1), json={
        "feedback": "reject",
        "itemIds": [str(red.id)],
        "reasonChips": ["color", "formality"],
        "directions": {"formality": "too_casual"},
    })
    assert r.status_code == 202
    body = r.json()
    assert body["eventType"] == "outfit_reject"
    assert body["signals"] >= 2

    keys = {s.key for s in _fb(db, user1)}
    assert {"color", "formality"} <= keys

    ev = db.query(StyleEvent).filter_by(event_type="outfit_reject").one()
    assert ev.user_id == user1.id
    assert ev.entity_type == "outfit"
    assert ev.properties["reason_chips"] == ["color", "formality"]
    assert ev.properties["formality_direction"] == "too_casual"
    # No PII: properties are flat scalars / short scalar lists only.
    for v in ev.properties.values():
        assert isinstance(v, (str, int, float, bool)) or (
            isinstance(v, list) and all(isinstance(x, (str, int, float, bool)) for x in v)
        )


def test_cannot_reference_another_users_item(client, db, user2, tok1):
    victim = _item(db, user2, color_primary="red")
    r = client.post("/outfits/feedback", headers=_auth(tok1), json={
        "feedback": "reject", "itemIds": [str(victim.id)], "reasonChips": ["color"],
    })
    assert r.status_code == 422
    assert db.query(StyleEvent).count() == 0  # nothing written on a failed-closed call


def test_unknown_reason_chip_rejected(client, tok1):
    r = client.post("/outfits/feedback", headers=_auth(tok1),
                    json={"feedback": "reject", "reasonChips": ["bogus"]})
    assert r.status_code == 422


def test_modify_requires_removed_and_replacement(client, db, user1, tok1):
    red = _item(db, user1, color_primary="red")
    r = client.post("/outfits/feedback", headers=_auth(tok1),
                    json={"feedback": "modify", "itemIds": [str(red.id)]})
    assert r.status_code == 422


def test_modify_endpoint_records_swap(client, db, user1, tok1):
    removed = _item(db, user1, color_primary="red", sub_category="loafer")
    repl = _item(db, user1, color_primary="blue", sub_category="sneaker")
    r = client.post("/outfits/feedback", headers=_auth(tok1), json={
        "feedback": "modify",
        "itemIds": [str(removed.id)],
        "removedItemId": str(removed.id),
        "replacementItemId": str(repl.id),
        "slot": "footwear",
    })
    assert r.status_code == 202
    ev = db.query(StyleEvent).filter_by(event_type="outfit_modify").one()
    assert ev.properties["slot"] == "footwear"
    keys = {(s.key, s.polarity) for s in _fb(db, user1)}
    assert ("color", "dislike") in keys and ("color", "like") in keys
    assert ("category", "dislike") in keys and ("category", "like") in keys


def test_worn_saved_outfit_updates_status_and_wear(client, db, user1, tok1):
    a = _item(db, user1, color_primary="olive")
    b = _item(db, user1, color_primary="rust")
    saved = SavedOutfit(user_id=user1.id, item_ids=[str(a.id), str(b.id)], source="chat")
    db.add(saved); db.commit(); db.refresh(saved)

    r = client.post("/outfits/feedback", headers=_auth(tok1),
                    json={"feedback": "worn", "savedOutfitId": str(saved.id)})
    assert r.status_code == 202
    assert r.json()["status"] == "worn"

    db.refresh(saved)
    assert saved.status == "worn" and saved.worn_at is not None
    db.refresh(a)
    assert a.wear_count == 1 and a.last_worn_at is not None

    sigs = _fb(db, user1)
    assert len(sigs) >= 2 and all(s.polarity == "like" for s in sigs)
    ev = db.query(StyleEvent).filter_by(event_type="outfit_worn").one()
    assert ev.entity_id == str(saved.id)


def test_feedback_isolated_to_caller(client, db, user1, user2, tok1):
    red = _item(db, user1, color_primary="red")
    r = client.post("/outfits/feedback", headers=_auth(tok1),
                    json={"feedback": "reject", "itemIds": [str(red.id)],
                          "reasonChips": ["color"]})
    assert r.status_code == 202
    assert _fb(db, user2) == []
    assert len(_fb(db, user1)) >= 1


# ===========================================================================
# Precedence: outfit_feedback outranks inferred, below explicit
# ===========================================================================
def test_outfit_feedback_outranks_inferred_in_the_vote(db, user1):
    now = datetime(2026, 7, 4, 12, 0, 0)
    # Equal base strength: an inferred LIKE vs an outfit_feedback DISLIKE.
    db.add(PreferenceSignal(user_id=user1.id, signal_type="chat_distilled", key="formality",
                            polarity="like", weight=0.8, source="chat_inferred", created_at=now))
    db.add(PreferenceSignal(user_id=user1.id, signal_type="outfit_feedback", key="formality",
                            polarity="dislike", weight=0.8, source="outfit_feedback", created_at=now))
    db.commit()

    recompute_preferences(db, user1.id, now)
    db.commit()
    row = db.query(StylePreference).filter_by(user_id=user1.id, dimension="formality").one()
    # 0.8*0.7 (feedback) beats 0.8*0.5 (inferred) -> net dislike.
    assert row.polarity == "dislike"
    assert row.source == "inferred"  # feedback is NOT user-stated -> never 'explicit'


def test_outfit_feedback_never_overwrites_explicit(db, user1):
    now = datetime(2026, 7, 4, 12, 0, 0)
    db.add(StylePreference(user_id=user1.id, dimension="color", value={}, polarity="like",
                           confidence=0.9, source="explicit", active=True, last_seen_at=now))
    db.add(PreferenceSignal(user_id=user1.id, signal_type="outfit_feedback", key="color",
                            polarity="dislike", weight=0.9, source="outfit_feedback", created_at=now))
    db.commit()

    _, upserted, protected = recompute_preferences(db, user1.id, now)
    db.commit()
    row = db.query(StylePreference).filter_by(user_id=user1.id, dimension="color").one()
    assert protected == 1 and upserted == 0
    assert row.polarity == "like" and row.source == "explicit"
