"""GET/PATCH /profile/style — the My Style Profile read/edit endpoints.

Covers the happy read/write paths, the whitelist (never leak un-rendered facts),
the SACRED-WRITE guarantee (a user edit survives distillation) and the TOMBSTONE
guarantee (a deleted preference never re-emerges from old signals), plus
cross-user isolation. Runs on the real SQLite substrate; no LLM on this path.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, engine
from app.models import PreferenceSignal, StylePreference, StyleProfile, User
from app.services.stylist.distill import decay_preferences, recompute_preferences
from tests._authutil import mint_supabase_token
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
    u = User(email="sp1@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture
def user2(db: Session):
    u = User(email="sp2@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture
def tok1(user1):
    return mint_supabase_token(sub=str(user1.id))


@pytest.fixture
def tok2(user2):
    return mint_supabase_token(sub=str(user2.id))


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---------------------------------------------------------------------------
# READ
# ---------------------------------------------------------------------------
def test_get_requires_auth(client):
    assert client.get("/profile/style").status_code == 401  # no bearer -> unauthenticated


def test_fresh_user_reads_empty_profile(client, tok1):
    r = client.get("/profile/style", headers=_auth(tok1))
    assert r.status_code == 200
    body = r.json()
    assert body["facts"] == {}
    assert body["narrative"] is None
    assert body["preferences"] == []
    assert body["onboardingCompletedAt"] is None
    assert body["version"] == 0


def test_get_returns_real_facts_narrative_and_prefs(client, db, user1, tok1):
    db.add(StyleProfile(
        user_id=user1.id,
        facts={
            "sizes": {"top": "M", "shoe": {"system": "EU", "value": "43"}},
            "fits": {"top": 2, "bottom": 4},
            "location": {"lat": 1.23, "lon": 4.56},   # NOT whitelisted -> must be hidden
            "never_wear": ["neon"],                     # NOT whitelisted -> hidden
            "onboarding_completed_at": "2026-06-01T00:00:00+00:00",
        },
        narrative_blob={"text": "Quiet minimal — neutral palette, relaxed fits.", "source": "distilled"},
        summary="Quiet minimal",
        version=3,
    ))
    db.add(StylePreference(
        user_id=user1.id, dimension="color", value={"notes": ["neutrals"]},
        polarity="like", confidence=0.94, source="inferred", evidence_count=212, active=True,
    ))
    db.add(StylePreference(
        user_id=user1.id, dimension="brand", value={}, polarity="dislike",
        confidence=0.2, source="inferred", evidence_count=0, active=False,  # inactive -> hidden
    ))
    db.commit()

    body = client.get("/profile/style", headers=_auth(tok1)).json()
    # Whitelist: sizes/fits exposed; location + never_wear + completion never leak into facts.
    assert set(body["facts"].keys()) == {"sizes", "fits"}
    assert body["facts"]["sizes"]["top"] == "M"
    # Narrative returned verbatim.
    assert body["narrative"] == "Quiet minimal — neutral palette, relaxed fits."
    assert body["summary"] == "Quiet minimal"
    assert body["onboardingCompletedAt"] == "2026-06-01T00:00:00+00:00"
    assert body["version"] == 3
    # Only the active preference; carries a derived explanation line.
    assert len(body["preferences"]) == 1
    pref = body["preferences"][0]
    assert pref["dimension"] == "color"
    assert pref["evidenceCount"] == 212
    assert "212" in pref["explanation"]
    assert pref["userEdited"] is False


# ---------------------------------------------------------------------------
# WRITE — facts
# ---------------------------------------------------------------------------
def test_patch_facts_merges_whitelisted_and_stamps_user_edited(client, db, user1, tok1):
    r = client.patch(
        "/profile/style",
        headers=_auth(tok1),
        json={"facts": {
            "sizes": {"top": "L"},
            "fit_preference": "Relaxed",
            "onboarding_completed_at": "hacked",   # server-owned, must be stripped
            "weight_kg": 80,                         # never-asked field, must be dropped
        }},
    )
    assert r.status_code == 200
    facts = r.json()["facts"]
    assert facts["sizes"]["top"] == "L"
    assert facts["fit_preference"] == "Relaxed"
    assert "weight_kg" not in facts
    assert "onboarding_completed_at" not in facts  # not whitelisted for exposure

    row = db.query(StyleProfile).filter(StyleProfile.user_id == user1.id).one()
    assert row.facts["_user_edited"] == {"sizes": True, "fit_preference": True}
    assert "weight_kg" not in row.facts          # never persisted
    assert row.facts.get("onboarding_completed_at") != "hacked"  # completion not forgeable


# ---------------------------------------------------------------------------
# WRITE — preference override (sacred) + delete (tombstone)
# ---------------------------------------------------------------------------
def test_patch_override_is_sacred(client, db, user1, tok1):
    r = client.patch(
        "/profile/style",
        headers=_auth(tok1),
        json={"preferences": [{"dimension": "color", "polarity": "dislike", "value": {"note": "no beige"}}]},
    )
    assert r.status_code == 200
    row = db.query(StylePreference).filter_by(user_id=user1.id, dimension="color").one()
    assert row.source == "explicit"
    assert row.active is True
    assert row.value["user_edited"] is True
    assert row.confidence == pytest.approx(0.9)

    # The internal marker is never echoed back as data.
    pref = next(p for p in r.json()["preferences"] if p["dimension"] == "color")
    assert "user_edited" not in pref["value"]
    assert pref["userEdited"] is True
    assert pref["explanation"] == "You set this yourself"


def test_override_survives_inferred_recompute(client, db, user1, tok1):
    client.patch(
        "/profile/style", headers=_auth(tok1),
        json={"preferences": [{"dimension": "color", "polarity": "like", "value": {}}]},
    )
    # A pile of inferred signals that would otherwise flip/rescore 'color'.
    for _ in range(5):
        db.add(PreferenceSignal(
            user_id=user1.id, signal_type="chat_distilled", key="color",
            polarity="dislike", source="chat_inferred", weight=1.0,
        ))
    db.commit()
    now = datetime.utcnow()
    recompute_preferences(db, user1.id, now)
    decay_preferences(db, user1.id, now)
    db.commit()

    row = db.query(StylePreference).filter_by(user_id=user1.id, dimension="color").one()
    assert row.polarity == "like"          # user's assertion untouched
    assert row.source == "explicit"
    assert row.active is True


def test_delete_tombstones_and_blocks_reemergence(client, db, user1, tok1):
    # Seed an inferred preference + the signals behind it.
    db.add(StylePreference(
        user_id=user1.id, dimension="brand", value={}, polarity="like",
        confidence=0.6, source="inferred", evidence_count=3, active=True,
    ))
    for _ in range(4):
        db.add(PreferenceSignal(
            user_id=user1.id, signal_type="chat_distilled", key="brand",
            polarity="like", source="chat_inferred", weight=1.0,
        ))
    db.commit()

    r = client.patch("/profile/style", headers=_auth(tok1),
                     json={"preferences": [{"dimension": "brand", "delete": True}]})
    assert r.status_code == 200
    # Gone from the read payload immediately.
    assert all(p["dimension"] != "brand" for p in r.json()["preferences"])

    db.expire_all()
    row = db.query(StylePreference).filter_by(user_id=user1.id, dimension="brand").one()
    assert row.active is False
    assert row.value["deleted"] is True and row.value["user_edited"] is True

    # Nightly recompute must NOT resurrect it from the old signals.
    now = datetime.utcnow()
    recompute_preferences(db, user1.id, now)
    db.commit()
    db.expire_all()
    row = db.query(StylePreference).filter_by(user_id=user1.id, dimension="brand").one()
    assert row.active is False
    assert all(p["dimension"] != "brand" for p in client.get("/profile/style", headers=_auth(tok1)).json()["preferences"])


def test_delete_unknown_dimension_creates_tombstone(client, db, user1, tok1):
    # No prior row for 'vibe' — the dimension may live only as raw signals.
    for _ in range(4):
        db.add(PreferenceSignal(
            user_id=user1.id, signal_type="chat_distilled", key="vibe",
            polarity="like", source="chat_inferred", weight=1.0,
        ))
    db.commit()
    client.patch("/profile/style", headers=_auth(tok1),
                 json={"preferences": [{"dimension": "vibe", "delete": True}]})
    now = datetime.utcnow()
    recompute_preferences(db, user1.id, now)
    db.commit()
    db.expire_all()
    row = db.query(StylePreference).filter_by(user_id=user1.id, dimension="vibe").one()
    assert row.active is False          # tombstone held the slot; never emerged


def test_invalid_dimension_rejected(client, tok1):
    r = client.patch("/profile/style", headers=_auth(tok1),
                     json={"preferences": [{"dimension": "not_a_dimension", "polarity": "like"}]})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# CROSS-USER ISOLATION
# ---------------------------------------------------------------------------
def test_isolation_reads_and_writes_are_per_user(client, db, user1, user2, tok1, tok2):
    db.add(StylePreference(
        user_id=user1.id, dimension="color", value={}, polarity="like",
        confidence=0.9, source="explicit", active=True,
    ))
    db.commit()

    # user2 sees NONE of user1's learned preferences.
    assert client.get("/profile/style", headers=_auth(tok2)).json()["preferences"] == []

    # user2 deleting 'color' creates user2's OWN tombstone, leaving user1 untouched.
    client.patch("/profile/style", headers=_auth(tok2),
                 json={"preferences": [{"dimension": "color", "delete": True}]})
    db.expire_all()
    rows = db.query(StylePreference).filter_by(dimension="color").all()
    by_user = {r.user_id: r for r in rows}
    assert by_user[user1.id].active is True          # untouched
    assert by_user[user2.id].active is False          # user2's own tombstone
    # user1 still sees their active preference.
    assert any(p["dimension"] == "color" for p in client.get("/profile/style", headers=_auth(tok1)).json()["preferences"])
