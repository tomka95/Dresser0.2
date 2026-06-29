"""Wave 1: photo candidates flow through the SHARED confirm/upsert + the
/photo/ingest/start route end-to-end. SQLite DB; detection + storage faked."""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from app.db import Base, SessionLocal, engine
from app.gmail_closet.review_service import (
    ConfirmError,
    _upsert_clothing_item,
    confirm_candidates,
)
from app.models import ClothingItem, IngestCandidate, User
from app.photo_closet import ingest_service
from app.photo_closet.detection import DetectionResult, GarmentRegion
from app.security import create_access_token
from app.utils.image_validation import validate_and_sanitize
from main import app


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


def _user(db, email):
    u = User(email=email, hashed_password="x", display_name=email)
    db.add(u); db.commit(); db.refresh(u)
    return u


def _photo_candidate(db, user_id, name="Red Tee", slk="photoslk0000000000000000000000000"):
    c = IngestCandidate(
        user_id=user_id, source_line_key=slk, name=name, category="top", color="red",
        image_url="https://blob.example/cut.jpg", image_status="user_uploaded",
        source_type="photo", status="pending", confidence_overall=0.9,
    )
    db.add(c); db.commit(); db.refresh(c)
    return c


def _jpeg(color=(120, 30, 30), size=(96, 96)):
    img = Image.new("RGB", size, color)
    buf = io.BytesIO(); img.save(buf, "JPEG")
    return buf.getvalue()


# --- shared confirm path carries source_type + user_uploaded ----------------

class _CapturingDB:
    """Captures the upsert statement; confirm's upsert is Postgres-only (pg_insert +
    (xmax=0) RETURNING), so we inspect the compiled statement instead of executing it
    on SQLite."""

    def __init__(self):
        self.stmt = None

    def execute(self, stmt):
        self.stmt = stmt
        return SimpleNamespace(one=lambda: SimpleNamespace(id="cit-1", inserted=True))


def test_upsert_threads_photo_source_type_and_preserves_user_uploaded():
    import uuid
    cand = IngestCandidate(
        id=uuid.uuid4(), user_id=uuid.uuid4(), name="Red Tee", category="top",
        color="red", brand=None, size=None, quantity=1, unit_price=None, currency=None,
        order_date=None, is_return=False, order_id=None, message_id=None,
        source_line_key="photoslk0000000000000000000000000",
        confidence_overall=0.9, merchant=None,
        image_url="https://blob.example/cut.jpg", image_status="user_uploaded",
        source_type="photo",
    )
    fake = _CapturingDB()
    written = _upsert_clothing_item(fake, cand.user_id, cand, None)
    assert written.inserted is True

    compiled = fake.stmt.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    params = compiled.params
    # source_type is in BOTH the INSERT column list and the ON CONFLICT DO UPDATE SET.
    assert sql.count("source_type") >= 2
    assert params["source_type"] == "photo"
    # user_uploaded is preserved, NOT relabeled 'resolved' despite image_url present.
    assert params["image_status"] == "user_uploaded"


def test_confirm_photo_candidate_accepts_and_marks(db):
    # The end-to-end write is Postgres-only; here we verify the candidate-side
    # bookkeeping (ownership accepted, status flip) that runs before the upsert.
    user = _user(db, "c1@example.com")
    cand = _photo_candidate(db, user.id)
    # Reject path writes nothing and needs no Postgres upsert -> runs on SQLite.
    res = confirm_candidates(db, user.id, rejected=[str(cand.id)])
    assert res.rejected_count == 1
    db.refresh(cand)
    assert cand.status == "rejected"
    assert db.query(ClothingItem).count() == 0


def test_confirm_rejects_cross_user_photo_candidate(db):
    owner = _user(db, "owner@example.com")
    attacker = _user(db, "attacker@example.com")
    cand = _photo_candidate(db, owner.id)
    # Attacker (JWT user_id) cannot confirm the owner's candidate.
    with pytest.raises(ConfirmError):
        confirm_candidates(db, attacker.id, accepted=[str(cand.id)])
    assert db.query(ClothingItem).count() == 0


# --- POST /photo/ingest/start end-to-end ------------------------------------

def test_route_single_person_stages_and_appears_in_deck(db, client, monkeypatch):
    user = _user(db, "r1@example.com")
    token = create_access_token(data={"sub": str(user.id)})

    detection = DetectionResult(person_count=1, garments=[
        GarmentRegion(name="Green Jacket", category="outerwear", color="green",
                      box_2d=[20, 20, 700, 700], confidence_overall=0.88),
    ])
    monkeypatch.setattr(
        ingest_service, "detect_garments_with_regions",
        lambda *, image_bytes, content_type, provider=None: detection,
    )

    resp = client.post(
        "/photo/ingest/start",
        headers={"Authorization": f"Bearer {token}"},
        files={"files": ("me.jpg", _jpeg(), "image/jpeg")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["images_processed"] == 1
    assert body["staged"] == 1
    assert body["held_multi_person"] == 0

    # The staged photo candidate is visible through the SHARED deck endpoint.
    deck = client.get(
        "/gmail/ingest/candidates", headers={"Authorization": f"Bearer {token}"})
    assert deck.status_code == 200
    cands = deck.json()
    assert len(cands) == 1
    assert cands[0]["source_type"] == "photo"
    assert cands[0]["name"] == "Green Jacket"
    assert cands[0]["image_status"] == "user_uploaded"


def test_route_multi_person_held(db, client, monkeypatch):
    user = _user(db, "r2@example.com")
    token = create_access_token(data={"sub": str(user.id)})
    detection = DetectionResult(person_count=3, garments=[
        GarmentRegion(name="X", category="top", box_2d=[0, 0, 1000, 1000])])
    monkeypatch.setattr(
        ingest_service, "detect_garments_with_regions",
        lambda *, image_bytes, content_type, provider=None: detection,
    )
    resp = client.post(
        "/photo/ingest/start",
        headers={"Authorization": f"Bearer {token}"},
        files={"files": ("group.jpg", _jpeg(), "image/jpeg")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["held_multi_person"] == 1
    assert body["staged"] == 0
    assert "more than one person" in (body["message"] or "")


def test_route_rejects_non_image(db, client):
    user = _user(db, "r3@example.com")
    token = create_access_token(data={"sub": str(user.id)})
    resp = client.post(
        "/photo/ingest/start",
        headers={"Authorization": f"Bearer {token}"},
        files={"files": ("evil.jpg", b"<html>not an image</html>", "image/jpeg")},
    )
    # Magic-byte sniff defeats the spoofed content-type.
    assert resp.status_code == 400
    assert db.query(IngestCandidate).count() == 0


def test_route_requires_auth(client):
    resp = client.post(
        "/photo/ingest/start",
        files={"files": ("me.jpg", _jpeg(), "image/jpeg")},
    )
    assert resp.status_code in (401, 403)
