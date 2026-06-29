"""Wave 1 photo-ingest orchestrator: detect -> crop -> stage, idempotency, and the
multi-person privacy hold. SQLite DB; detection + cutout upload are faked."""
from __future__ import annotations

import io

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, engine
from app.models import IngestCandidate, IngestRun, ProcessedUpload, User
from app.photo_closet import ingest_service
from app.photo_closet.detection import DetectionResult, GarmentRegion
from app.utils.image_validation import validate_and_sanitize


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
def user(db: Session):
    u = User(email="p@example.com", hashed_password="x", display_name="P")
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture(autouse=True)
def _fake_upload(monkeypatch):
    # Avoid the real get_or_upload (Postgres ON CONFLICT) on the SQLite test DB.
    monkeypatch.setattr(
        ingest_service, "store_cutout",
        lambda sc, uid, cut: "https://blob.example/cutout.jpg",
    )


def _sanitized(color=(120, 30, 30), size=(128, 128), fmt="JPEG"):
    img = Image.new("RGB", size, color)
    buf = io.BytesIO(); img.save(buf, fmt)
    return validate_and_sanitize(buf.getvalue())


def _banded(fmt="PNG"):
    img = Image.new("RGB", (128, 128))
    for x in range(128):
        v = 255 if (x // 8) % 2 == 0 else 0
        for y in range(128):
            img.putpixel((x, y), (v, v, v))
    buf = io.BytesIO(); img.save(buf, fmt, quality=88)
    return validate_and_sanitize(buf.getvalue())


def _detect_returning(result: DetectionResult):
    def _detect(*, image_bytes, content_type, provider=None):
        return result
    return _detect


def _garment(name, cat="top", box=(0, 0, 1000, 1000), color="red", conf=0.9):
    return GarmentRegion(
        name=name, category=cat, color=color, box_2d=list(box), confidence_overall=conf,
    )


def test_single_person_two_garments_stage(db, user):
    detection = DetectionResult(person_count=1, garments=[
        _garment("Red Tee", "top", (50, 50, 500, 600)),
        _garment("Blue Jeans", "bottom", (500, 80, 980, 560), color="blue"),
    ])
    res = ingest_service.ingest_photos(
        db, user.id, [_sanitized()], detect=_detect_returning(detection),
    )
    assert res.images_processed == 1
    assert res.staged == 2
    assert res.held_multi_person == 0

    cands = db.query(IngestCandidate).filter(IngestCandidate.user_id == user.id).all()
    assert len(cands) == 2
    for c in cands:
        assert c.source_type == "photo"
        assert c.image_status == "user_uploaded"
        assert c.status == "pending"
        assert c.message_id is None
        assert c.image_url == "https://blob.example/cutout.jpg"
        assert c.source_line_key and len(c.source_line_key) == 32

    run = db.query(IngestRun).filter(IngestRun.sync_id == res.sync_id).one()
    assert run.status == "completed"
    assert run.source_type == "photo"
    assert run.extracted_count == 2

    pu = db.query(ProcessedUpload).filter(ProcessedUpload.user_id == user.id).one()
    assert pu.status == "processed" and pu.item_count == 2


def test_multi_person_held_not_guessed(db, user):
    detection = DetectionResult(person_count=2, garments=[_garment("X")])
    res = ingest_service.ingest_photos(
        db, user.id, [_sanitized()], detect=_detect_returning(detection),
    )
    assert res.held_multi_person == 1
    assert res.staged == 0
    assert db.query(IngestCandidate).count() == 0
    pu = db.query(ProcessedUpload).filter(ProcessedUpload.user_id == user.id).one()
    assert pu.status == "held_multi_person" and pu.item_count == 0


def test_exact_reupload_is_idempotent(db, user):
    img = _sanitized()
    detection = DetectionResult(person_count=1, garments=[_garment("Tee")])
    d = _detect_returning(detection)
    ingest_service.ingest_photos(db, user.id, [img], detect=d)
    # Same bytes again -> recognized as duplicate, nothing reprocessed.
    res2 = ingest_service.ingest_photos(db, user.id, [img], detect=d)
    assert res2.duplicates == 1 and res2.staged == 0
    assert db.query(IngestCandidate).count() == 1


def test_near_duplicate_skipped(db, user):
    png = _banded("PNG")     # processed first
    jpg = _banded("JPEG")    # same picture, different bytes -> near-dup by phash
    assert png.sha256 != jpg.sha256
    detection = DetectionResult(person_count=1, garments=[_garment("Striped")])
    d = _detect_returning(detection)
    ingest_service.ingest_photos(db, user.id, [png], detect=d)
    res2 = ingest_service.ingest_photos(db, user.id, [jpg], detect=d)
    assert res2.duplicates == 1 and res2.staged == 0


def test_identical_boxes_collapse_to_one_candidate(db, user):
    # Two garments with the SAME region -> same source_line_key -> one candidate.
    detection = DetectionResult(person_count=1, garments=[
        _garment("A", box=(10, 10, 900, 900)),
        _garment("B", box=(10, 10, 900, 900)),
    ])
    res = ingest_service.ingest_photos(
        db, user.id, [_sanitized()], detect=_detect_returning(detection),
    )
    assert db.query(IngestCandidate).count() == 1
    # res.staged counts both passes; the unique key collapses them in the DB.
    assert res.staged == 2


def test_unusable_box_skipped(db, user):
    detection = DetectionResult(person_count=1, garments=[
        _garment("Good", box=(0, 0, 1000, 1000)),
        _garment("Bad", box=(0, 0, 0, 0)),  # zero-area -> skipped by build_cutout
    ])
    res = ingest_service.ingest_photos(
        db, user.id, [_sanitized()], detect=_detect_returning(detection),
    )
    assert res.staged == 1
    assert db.query(IngestCandidate).count() == 1
