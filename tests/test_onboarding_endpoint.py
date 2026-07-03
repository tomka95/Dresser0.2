"""Tests for POST /onboarding/seed + GET /onboarding/status (Wave S1)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import SessionLocal, Base, engine
from app.models import PreferenceSignal, StylePreference, StyleProfile, User
from app.security import create_access_token
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
    return create_access_token(data={"sub": str(user1.id)})


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


# --- auth -------------------------------------------------------------------
def test_seed_requires_auth(client):
    assert client.post("/onboarding/seed", json={}).status_code == 401


def test_status_requires_auth(client):
    assert client.get("/onboarding/status").status_code == 401


# --- happy path -------------------------------------------------------------
def test_seed_writes_all_three_tables_and_stamps_completion(client, db, user1, tok1):
    r = client.post(
        "/onboarding/seed",
        headers=_auth(tok1),
        json={
            "facts": {"department": "womens", "sizes": {"top": "M"}, "fits": {"top": 4}},
            "preferences": [
                {"dimension": "occasion", "value": {"tags": ["work", "casual"]}, "polarity": "like"},
            ],
            "signals": [
                {"signalType": "taste_swipe", "key": "minimal", "polarity": "like", "weight": 1.0},
                {"signalType": "taste_swipe", "key": "edgy", "polarity": "dislike", "weight": 1.0},
            ],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["preferencesUpserted"] == 1
    assert body["signalsInserted"] == 2

    prof = db.query(StyleProfile).filter(StyleProfile.user_id == user1.id).one()
    assert prof.facts["department"] == "womens"
    assert prof.facts["onboarding_completed_at"]  # server-stamped
    assert db.query(StylePreference).filter(StylePreference.user_id == user1.id).count() == 1
    assert db.query(PreferenceSignal).filter(PreferenceSignal.user_id == user1.id).count() == 2

    # status now reports complete
    s = client.get("/onboarding/status", headers=_auth(tok1))
    assert s.status_code == 200 and s.json()["completed"] is True


def test_status_false_before_seed(client, tok1):
    assert client.get("/onboarding/status", headers=_auth(tok1)).json()["completed"] is False


# --- security ---------------------------------------------------------------
def test_source_is_forced_onboarding(client, db, user1, tok1):
    # A client-sent source (extra=ignore) must not override 'onboarding'.
    client.post(
        "/onboarding/seed",
        headers=_auth(tok1),
        json={"preferences": [{"dimension": "color", "source": "explicit"}]},
    )
    pref = db.query(StylePreference).filter(StylePreference.user_id == user1.id).one()
    assert pref.source == "onboarding"


def test_confidence_clamped_into_band(client, db, user1, tok1):
    client.post(
        "/onboarding/seed",
        headers=_auth(tok1),
        json={"preferences": [{"dimension": "color", "confidence": 0.99}]},
    )
    pref = db.query(StylePreference).filter(StylePreference.user_id == user1.id).one()
    assert 0.5 <= pref.confidence <= 0.6


def test_client_cannot_forge_completion_flag(client, db, user1, tok1):
    # A forged onboarding_completed_at in facts must be stripped; the server value
    # is a real ISO timestamp, not the injected sentinel.
    client.post(
        "/onboarding/seed",
        headers=_auth(tok1),
        json={"facts": {"onboarding_completed_at": "HACKED"}},
    )
    prof = db.query(StyleProfile).filter(StyleProfile.user_id == user1.id).one()
    assert prof.facts["onboarding_completed_at"] != "HACKED"


def test_signals_never_take_client_item_ref(client, db, user1, tok1):
    client.post(
        "/onboarding/seed",
        headers=_auth(tok1),
        json={"signals": [{"signalType": "taste_swipe", "key": "x", "item_id": "whatever"}]},
    )
    sig = db.query(PreferenceSignal).filter(PreferenceSignal.user_id == user1.id).one()
    assert sig.item_id is None and sig.event_id is None
    assert sig.evidence_ref == "onboarding"


def test_invalid_polarity_rejected(client, tok1):
    r = client.post(
        "/onboarding/seed",
        headers=_auth(tok1),
        json={"preferences": [{"dimension": "color", "polarity": "love"}]},
    )
    assert r.status_code == 422


# --- caps -------------------------------------------------------------------
def test_preferences_cap_enforced(client, tok1):
    from app.core.config import settings
    over = [{"dimension": f"d{i}"} for i in range(settings.ONBOARDING_MAX_PREFERENCES + 1)]
    r = client.post("/onboarding/seed", headers=_auth(tok1), json={"preferences": over})
    assert r.status_code == 422


def test_signals_cap_enforced(client, tok1):
    from app.core.config import settings
    over = [{"signalType": "taste_swipe"} for _ in range(settings.ONBOARDING_MAX_SIGNALS + 1)]
    r = client.post("/onboarding/seed", headers=_auth(tok1), json={"signals": over})
    assert r.status_code == 422


# --- idempotency (re-run must not 409) --------------------------------------
def test_reseed_is_idempotent_upsert(client, db, user1, tok1):
    payload = {
        "facts": {"department": "womens"},
        "preferences": [{"dimension": "occasion", "polarity": "like"}],
    }
    r1 = client.post("/onboarding/seed", headers=_auth(tok1), json=payload)
    assert r1.status_code == 201
    # second run: department changes, same dimension -> update in place, no 409
    payload["facts"]["department"] = "mens"
    payload["preferences"][0]["polarity"] = "neutral"
    r2 = client.post("/onboarding/seed", headers=_auth(tok1), json=payload)
    assert r2.status_code == 201

    assert db.query(StyleProfile).filter(StyleProfile.user_id == user1.id).count() == 1
    prof = db.query(StyleProfile).filter(StyleProfile.user_id == user1.id).one()
    assert prof.facts["department"] == "mens"
    prefs = db.query(StylePreference).filter(StylePreference.user_id == user1.id).all()
    assert len(prefs) == 1  # upserted, not duplicated
    assert prefs[0].polarity == "neutral"
    assert prefs[0].evidence_count == 2  # reinforced across two seeds
