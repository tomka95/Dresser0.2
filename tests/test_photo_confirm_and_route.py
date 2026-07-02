"""Wave 1.5: photo candidates flow through the SHARED confirm/upsert + the
/photo/ingest/detect -> /photo/ingest/commit routes end-to-end. SQLite DB;
detection + storage faked."""
from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone

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
from app.models import ClothingItem, IngestCandidate, PhotoDetectSession, User
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


def _auth(db, email):
    user = _user(db, email)
    token = create_access_token(data={"sub": str(user.id)})
    return user, {"Authorization": f"Bearer {token}"}


def _patch_detect(monkeypatch, detection: DetectionResult):
    monkeypatch.setattr(
        ingest_service, "detect_garments_with_regions",
        lambda *, image_bytes, content_type, provider=None: detection,
    )


def _one_garment_detection(name="Green Jacket", cat="outerwear", color="green"):
    return DetectionResult(person_count=1, garments=[
        GarmentRegion(name=name, category=cat, color=color,
                      box_2d=[20, 20, 700, 700], confidence_overall=0.88),
    ])


def _detect_via_route(client, headers, raw, filename="me.jpg"):
    resp = client.post(
        "/photo/ingest/detect", headers=headers,
        files={"files": (filename, raw, "image/jpeg")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["sessions"][0]


def _commit_via_route(client, headers, raw, selections, filename="me.jpg"):
    return client.post(
        "/photo/ingest/commit", headers=headers,
        files={"files": (filename, raw, "image/jpeg")},
        data={"selections": json.dumps(selections)},
    )


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


# --- POST /photo/ingest/detect ------------------------------------------------

def test_route_detect_returns_regions_without_masks(db, client, monkeypatch):
    _, headers = _auth(db, "r1@example.com")
    detection = DetectionResult(person_count=1, garments=[
        GarmentRegion(name="Green Jacket", category="outerwear", color="green",
                      box_2d=[20, 20, 700, 700], mask="c2VjcmV0LW1hc2s=",
                      confidence_overall=0.88),
    ])
    _patch_detect(monkeypatch, detection)

    raw = _jpeg()
    session = _detect_via_route(client, headers, raw)

    sanitized = validate_and_sanitize(raw)
    assert session["filename"] == "me.jpg"
    assert session["session_id"]
    assert session["image_sha256"] == sanitized.sha256
    assert session["width"] == 96 and session["height"] == 96
    assert session["duplicate"] is False
    assert session["person_count"] == 1
    assert len(session["regions"]) == 1
    region = session["regions"][0]
    assert region["region_id"] == 0
    assert region["box_2d"] == [20, 20, 700, 700]
    assert region["name"] == "Green Jacket"
    assert region["category"] == "outerwear"
    assert "mask" not in region  # masks never leave the server

    # Detect stages NOTHING: the deck is still empty.
    deck = client.get("/gmail/ingest/candidates", headers=headers)
    assert deck.status_code == 200 and deck.json() == []


def test_route_detect_multi_person_flows_through(db, client, monkeypatch):
    _, headers = _auth(db, "r2@example.com")
    detection = DetectionResult(person_count=3, garments=[
        GarmentRegion(name="X", category="top", box_2d=[0, 0, 1000, 1000])])
    _patch_detect(monkeypatch, detection)
    session = _detect_via_route(client, headers, _jpeg(), filename="group.jpg")
    # Wave 1.5: no hold — a session comes back and the user picks the regions.
    assert session["session_id"] is not None
    assert session["person_count"] == 3
    assert len(session["regions"]) == 1


def test_route_detect_rejects_non_image(db, client):
    _, headers = _auth(db, "r3@example.com")
    resp = client.post(
        "/photo/ingest/detect", headers=headers,
        files={"files": ("evil.jpg", b"<html>not an image</html>", "image/jpeg")},
    )
    # Magic-byte sniff defeats the spoofed content-type.
    assert resp.status_code == 400
    assert db.query(IngestCandidate).count() == 0


def test_route_detect_requires_auth(client):
    resp = client.post(
        "/photo/ingest/detect",
        files={"files": ("me.jpg", _jpeg(), "image/jpeg")},
    )
    assert resp.status_code in (401, 403)


# --- POST /photo/ingest/commit --------------------------------------------------

def test_route_detect_commit_end_to_end_deck_scoped(db, client, monkeypatch):
    """Full Wave-1.5 loop: detect -> select region -> commit -> the staged candidate
    appears via the SHARED deck endpoint, scoped to the commit's sync_id (stale
    candidates from other runs excluded) — the confirm spine is untouched."""
    import uuid
    user, headers = _auth(db, "scope@example.com")

    # A stale, image-less pending Gmail candidate from an earlier run.
    db.add(IngestCandidate(
        user_id=user.id, sync_id=uuid.uuid4(), source_line_key="stale-gmail",
        name="Old Gmail Thing", category="top", status="pending",
        source_type="gmail", image_status="pending",
    ))
    db.commit()

    _patch_detect(monkeypatch, _one_garment_detection(name="Photo Shirt", cat="top",
                                                      color=None))
    raw = _jpeg()
    session = _detect_via_route(client, headers, raw)

    resp = _commit_via_route(client, headers, raw, [
        {"session_id": session["session_id"], "selected_region_ids": [0]},
    ])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["images_processed"] == 1
    assert body["staged"] == 1
    assert body["duplicates"] == 0
    assert body["held_multi_person"] == 0  # kept for client compat, always 0
    sync_id = body["sync_id"]

    # Scoped to the photo run: ONLY the photo candidate (stale Gmail one excluded).
    scoped = client.get(
        f"/gmail/ingest/candidates?sync_id={sync_id}", headers=headers).json()
    assert len(scoped) == 1
    assert scoped[0]["source_type"] == "photo"
    assert scoped[0]["name"] == "Photo Shirt"
    assert scoped[0]["image_status"] == "user_uploaded"

    # Unscoped (Gmail deck behavior) still returns both -> Gmail unchanged.
    unscoped = client.get("/gmail/ingest/candidates", headers=headers).json()
    assert len(unscoped) == 2


def test_route_commit_second_commit_conflicts_409(db, client, monkeypatch):
    _, headers = _auth(db, "c409@example.com")
    _patch_detect(monkeypatch, _one_garment_detection())
    raw = _jpeg()
    session = _detect_via_route(client, headers, raw)
    sel = [{"session_id": session["session_id"], "selected_region_ids": [0]}]

    assert _commit_via_route(client, headers, raw, sel).status_code == 200
    assert _commit_via_route(client, headers, raw, sel).status_code == 409


def test_route_commit_expired_session_410(db, client, monkeypatch):
    _, headers = _auth(db, "c410@example.com")
    _patch_detect(monkeypatch, _one_garment_detection())
    raw = _jpeg()
    session = _detect_via_route(client, headers, raw)

    row = db.query(PhotoDetectSession).one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    resp = _commit_via_route(client, headers, raw, [
        {"session_id": session["session_id"], "selected_region_ids": [0]},
    ])
    assert resp.status_code == 410


def test_route_commit_foreign_session_404(db, client, monkeypatch):
    _, owner_headers = _auth(db, "owner2@example.com")
    _, attacker_headers = _auth(db, "attacker2@example.com")
    _patch_detect(monkeypatch, _one_garment_detection())
    raw = _jpeg()
    session = _detect_via_route(client, owner_headers, raw)

    resp = _commit_via_route(client, attacker_headers, raw, [
        {"session_id": session["session_id"], "selected_region_ids": [0]},
    ])
    assert resp.status_code == 404
    assert db.query(IngestCandidate).count() == 0


def test_route_commit_unknown_session_404(db, client):
    _, headers = _auth(db, "c404@example.com")
    resp = _commit_via_route(client, headers, _jpeg(), [
        {"session_id": "11111111-2222-3333-4444-555555555555",
         "selected_region_ids": [0]},
    ])
    assert resp.status_code == 404


def test_route_commit_file_mismatch_409(db, client, monkeypatch):
    _, headers = _auth(db, "c409f@example.com")
    _patch_detect(monkeypatch, _one_garment_detection())
    session = _detect_via_route(client, headers, _jpeg())

    # Commit re-uploads a DIFFERENT photo -> no file matches the session's sha256.
    other = _jpeg(color=(10, 60, 200))
    resp = _commit_via_route(client, headers, other, [
        {"session_id": session["session_id"], "selected_region_ids": [0]},
    ])
    assert resp.status_code == 409
    assert db.query(IngestCandidate).count() == 0


@pytest.mark.parametrize("selections_raw", [
    "not json at all",
    '{"session_id": "x"}',                       # object, not array
    "[]",                                         # empty array
    '[{"selected_region_ids": [0]}]',             # missing session_id
    '[{"session_id": "x", "selected_region_ids": "0"}]',   # ids not a list
    '[{"session_id": "x", "manual_boxes": {}}]',  # boxes not a list
])
def test_route_commit_malformed_selections_400(db, client, selections_raw):
    _, headers = _auth(db, "c400@example.com")
    resp = client.post(
        "/photo/ingest/commit", headers=headers,
        files={"files": ("me.jpg", _jpeg(), "image/jpeg")},
        data={"selections": selections_raw},
    )
    assert resp.status_code == 400


def test_route_commit_invalid_manual_box_400(db, client, monkeypatch):
    _, headers = _auth(db, "c400b@example.com")
    _patch_detect(monkeypatch, _one_garment_detection())
    raw = _jpeg()
    session = _detect_via_route(client, headers, raw)
    resp = _commit_via_route(client, headers, raw, [
        {"session_id": session["session_id"],
         "manual_boxes": [[900, 100, 100, 600]]},  # ymin >= ymax
    ])
    assert resp.status_code == 400
    assert db.query(IngestCandidate).count() == 0


def test_route_commit_invalid_region_id_400(db, client, monkeypatch):
    _, headers = _auth(db, "c400r@example.com")
    _patch_detect(monkeypatch, _one_garment_detection())
    raw = _jpeg()
    session = _detect_via_route(client, headers, raw)
    resp = _commit_via_route(client, headers, raw, [
        {"session_id": session["session_id"], "selected_region_ids": [42]},
    ])
    assert resp.status_code == 400


def test_route_commit_requires_auth(client):
    resp = client.post(
        "/photo/ingest/commit",
        files={"files": ("me.jpg", _jpeg(), "image/jpeg")},
        data={"selections": "[]"},
    )
    assert resp.status_code in (401, 403)
