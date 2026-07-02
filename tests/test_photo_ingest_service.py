"""Wave 1.5 photo-ingest orchestrator: detect -> session, select -> commit-staged,
idempotency, and the session error taxonomy. SQLite DB; detection + upload faked."""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, engine
from app.models import (
    IngestCandidate,
    IngestRun,
    PhotoDetectSession,
    ProcessedUpload,
    User,
)
from app.photo_closet import ingest_service
from app.photo_closet.detection import (
    DetectionResult,
    GarmentDescription,
    GarmentRegion,
)
from app.photo_closet.ingest_service import (
    PhotoSelection,
    PhotoSelectionInvalid,
    PhotoSessionConflict,
    PhotoSessionExpired,
    PhotoSessionNotFound,
    _source_line_key,
)
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


def _detect_returning(result: DetectionResult, calls=None):
    def _detect(*, image_bytes, content_type, provider=None):
        if calls is not None:
            calls.append(content_type)
        return result
    return _detect


def _garment(name, cat="top", box=(0, 0, 1000, 1000), color="red", conf=0.9,
             mask=None):
    return GarmentRegion(
        name=name, category=cat, color=color, box_2d=list(box),
        confidence_overall=conf, mask=mask,
    )


def _two_garment_detection():
    return DetectionResult(person_count=1, garments=[
        _garment("Red Tee", "top", (50, 50, 500, 600), mask="bm90LWEtcmVhbC1wbmc="),
        _garment("Blue Jeans", "bottom", (500, 80, 980, 560), color="blue"),
    ])


def _detect_one(db, user, sanitized, detection):
    """Run detect for one photo; return its PhotoDetectOutcome."""
    outcomes = ingest_service.run_photo_detect(
        db, user.id, [sanitized], detect=_detect_returning(detection),
    )
    assert len(outcomes) == 1
    return outcomes[0]


# --- run_photo_detect ---------------------------------------------------------

def test_detect_creates_session_with_regions_and_no_masks(db, user):
    img = _sanitized()
    out = _detect_one(db, user, img, _two_garment_detection())

    assert out.duplicate is False
    assert out.session_id is not None
    assert out.image_sha256 == img.sha256
    assert (out.width, out.height) == (img.width, img.height)
    assert out.person_count == 1
    assert [r["region_id"] for r in out.regions] == [0, 1]
    assert out.regions[0]["box_2d"] == [50, 50, 500, 600]
    assert out.regions[0]["name"] == "Red Tee"
    assert out.regions[1]["category"] == "bottom"
    # Masks never leave the server.
    assert all("mask" not in r for r in out.regions)

    s = db.query(PhotoDetectSession).one()
    assert str(s.id) == out.session_id
    assert s.user_id == user.id
    assert s.status == "pending"
    assert s.image_sha256 == img.sha256 and s.phash == img.phash
    assert s.person_count == 1
    # The mask IS persisted in the session row (commit reads it for the cutout).
    assert s.regions[0]["mask"] == "bm90LWEtcmVhbC1wbmc="
    assert s.regions[1]["mask"] is None

    # Detect writes NOTHING else: no ledger, no run, no candidates, no storage.
    assert db.query(ProcessedUpload).count() == 0
    assert db.query(IngestRun).count() == 0
    assert db.query(IngestCandidate).count() == 0


def test_detect_duplicate_photo_skips_gemini_and_session(db, user):
    img = _sanitized()
    db.add(ProcessedUpload(
        user_id=user.id, sync_id=None, image_sha256=img.sha256, phash=img.phash,
        status="processed", item_count=1,
    ))
    db.commit()

    calls = []
    outcomes = ingest_service.run_photo_detect(
        db, user.id, [img],
        detect=_detect_returning(_two_garment_detection(), calls=calls),
    )
    out = outcomes[0]
    assert out.duplicate is True
    assert out.session_id is None
    assert out.regions == []
    assert calls == []  # no Gemini call for a duplicate
    assert db.query(PhotoDetectSession).count() == 0


def test_detect_near_duplicate_also_skipped(db, user):
    png = _banded("PNG")
    jpg = _banded("JPEG")  # same picture, different bytes -> near-dup by phash
    assert png.sha256 != jpg.sha256
    db.add(ProcessedUpload(
        user_id=user.id, sync_id=None, image_sha256=png.sha256, phash=png.phash,
        status="processed", item_count=1,
    ))
    db.commit()
    out = _detect_one(db, user, jpg, _two_garment_detection())
    assert out.duplicate is True and out.session_id is None


def test_detect_multi_person_flows_through(db, user):
    detection = DetectionResult(person_count=3, garments=[_garment("X")])
    out = _detect_one(db, user, _sanitized(), detection)
    # Wave 1.5: no hold — the user disambiguates by selecting regions.
    assert out.duplicate is False
    assert out.session_id is not None
    assert out.person_count == 3
    assert db.query(PhotoDetectSession).one().person_count == 3
    assert db.query(ProcessedUpload).count() == 0  # no held_multi_person ledger row


def test_detect_twice_upserts_one_pending_session(db, user):
    img = _sanitized()
    out1 = _detect_one(db, user, img, _two_garment_detection())
    second = DetectionResult(person_count=0, garments=[
        _garment("Only One", "dress", (10, 10, 800, 800)),
    ])
    out2 = _detect_one(db, user, img, second)

    assert out2.duplicate is False  # pending session != processed ledger
    assert out2.session_id == out1.session_id
    s = db.query(PhotoDetectSession).one()  # exactly one row
    assert len(s.regions) == 1 and s.regions[0]["name"] == "Only One"
    assert s.person_count == 0
    assert db.query(ProcessedUpload).count() == 0


def test_detect_sweeps_expired_pending_sessions(db, user):
    old_img = _sanitized(color=(10, 200, 40))
    _detect_one(db, user, old_img, _two_garment_detection())
    stale = db.query(PhotoDetectSession).one()
    stale.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()

    new_img = _banded()
    out = _detect_one(db, user, new_img, _two_garment_detection())
    remaining = db.query(PhotoDetectSession).all()
    assert len(remaining) == 1
    assert str(remaining[0].id) == out.session_id
    assert remaining[0].image_sha256 == new_img.sha256


def test_detect_multiple_photos_concurrently_preserves_order(db, user):
    """A multi-photo upload detects concurrently but returns outcomes in INPUT ORDER,
    one session per photo, each with its regions."""
    a = _sanitized(color=(200, 30, 30))
    b = _sanitized(color=(30, 30, 200))
    c = _banded()
    assert len({a.sha256, b.sha256, c.sha256}) == 3  # three distinct photos

    calls: list = []
    outcomes = ingest_service.run_photo_detect(
        db, user.id, [a, b, c],
        detect=_detect_returning(_two_garment_detection(), calls=calls),
    )

    assert [o.image_sha256 for o in outcomes] == [a.sha256, b.sha256, c.sha256]
    assert all(o.session_id for o in outcomes)
    assert all(len(o.regions) == 2 for o in outcomes)   # two garments each
    assert len(calls) == 3                              # each non-dup detected once
    assert db.query(PhotoDetectSession).count() == 3


def _striped(period):
    """A vertically-STRIPED photo: alternating bands give a varied (non-flat) phash, so it
    never collides with a solid image (whose dHash is all-zero, like a monotonic gradient).
    Different periods → distinct bytes AND distinct phashes."""
    img = Image.new("RGB", (128, 128))
    for x in range(128):
        v = 255 if (x // period) % 2 == 0 else 0
        for y in range(128):
            img.putpixel((x, y), (v, v, v))
    buf = io.BytesIO(); img.save(buf, "PNG")
    return validate_and_sanitize(buf.getvalue())


def test_detect_concurrent_skips_duplicate_in_batch(db, user):
    """A duplicate mixed into a concurrent batch is flagged (no Gemini call, no session);
    order is preserved and the other photos still detect."""
    a = _striped(6)
    dup = _sanitized(color=(50, 50, 50))
    c = _striped(12)
    db.add(ProcessedUpload(
        user_id=user.id, sync_id=None, image_sha256=dup.sha256, phash=dup.phash,
        status="processed", item_count=1,
    ))
    db.commit()

    calls: list = []
    outcomes = ingest_service.run_photo_detect(
        db, user.id, [a, dup, c],
        detect=_detect_returning(_two_garment_detection(), calls=calls),
    )

    assert [o.duplicate for o in outcomes] == [False, True, False]  # order preserved
    assert outcomes[1].session_id is None                          # dup: no session
    assert len(calls) == 2                                         # dup NOT detected
    assert db.query(PhotoDetectSession).count() == 2


# --- run_photo_commit -----------------------------------------------------------

def _commit(db, user, sanitized_images, selections, describe=None):
    by_sha = {s.sha256: s for s in sanitized_images}
    return ingest_service.run_photo_commit(
        db, user.id, None, by_sha, selections, describe=describe,
    )


def test_commit_stages_only_selected_regions(db, user):
    img = _sanitized()
    detection = DetectionResult(person_count=1, garments=[
        _garment("Red Tee", "top", (50, 50, 500, 600)),
        _garment("Blue Jeans", "bottom", (500, 80, 980, 560), color="blue"),
        _garment("Green Coat", "outerwear", (20, 600, 900, 990), color="green"),
    ])
    out = _detect_one(db, user, img, detection)

    res = _commit(db, user, [img], [
        PhotoSelection(session_id=out.session_id, selected_region_ids=[0, 2]),
    ])
    assert res.images_processed == 1
    assert res.staged == 2
    assert res.duplicates == 0

    cands = db.query(IngestCandidate).filter(IngestCandidate.user_id == user.id).all()
    assert len(cands) == 2
    staged_keys = {c.source_line_key for c in cands}
    assert staged_keys == {
        _source_line_key(img.sha256, [50, 50, 500, 600]),
        _source_line_key(img.sha256, [20, 600, 900, 990]),
    }
    # The unselected middle region was NOT staged.
    assert _source_line_key(img.sha256, [500, 80, 980, 560]) not in staged_keys
    for c in cands:
        assert c.source_type == "photo"
        assert c.image_status == "user_uploaded"
        assert c.status == "pending"
        assert c.message_id is None
        assert c.image_url == "https://blob.example/cutout.jpg"

    run = db.query(IngestRun).one()
    assert str(run.sync_id) == res.sync_id
    assert run.status == "completed" and run.source_type == "photo"
    assert run.extracted_count == 2

    pu = db.query(ProcessedUpload).one()
    assert pu.status == "processed" and pu.item_count == 2
    assert pu.image_sha256 == img.sha256 and pu.phash == img.phash

    assert db.query(PhotoDetectSession).one().status == "committed"


def test_commit_defers_completion_for_generation(db, user):
    """defer_completion + staged>0: the run stays 'running' so the background
    generation job (not the commit) finalizes it — the deck's generation-in-flight
    signal. extracted_count is still recorded; finished_at is left null."""
    img = _sanitized()
    detection = DetectionResult(person_count=1, garments=[
        _garment("Red Tee", "top", (50, 50, 500, 600)),
    ])
    out = _detect_one(db, user, img, detection)
    res = ingest_service.run_photo_commit(
        db, user.id, None, {img.sha256: img},
        [PhotoSelection(session_id=out.session_id, selected_region_ids=[0])],
        defer_completion=True,
    )
    assert res.staged == 1
    run = db.query(IngestRun).filter(IngestRun.sync_id == res.sync_id).one()
    assert run.status == "running"        # deferred — generation owns finalization
    assert run.finished_at is None
    assert run.extracted_count == 1


def test_commit_defer_but_nothing_staged_completes(db, user):
    """defer_completion is moot when nothing stages (all deselected): with no
    generation job to run, the commit finalizes the run itself."""
    img = _sanitized()
    out = _detect_one(db, user, img, _two_garment_detection())
    res = ingest_service.run_photo_commit(
        db, user.id, None, {img.sha256: img},
        [PhotoSelection(session_id=out.session_id, selected_region_ids=[])],
        defer_completion=True,
    )
    assert res.staged == 0
    run = db.query(IngestRun).filter(IngestRun.sync_id == res.sync_id).one()
    assert run.status == "completed" and run.finished_at is not None


def test_commit_same_session_twice_conflicts(db, user):
    img = _sanitized()
    out = _detect_one(db, user, img, _two_garment_detection())
    sel = [PhotoSelection(session_id=out.session_id, selected_region_ids=[0])]
    _commit(db, user, [img], sel)
    with pytest.raises(PhotoSessionConflict):
        _commit(db, user, [img], sel)


def test_commit_expired_session_gone(db, user):
    img = _sanitized()
    out = _detect_one(db, user, img, _two_garment_detection())
    s = db.query(PhotoDetectSession).one()
    s.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    with pytest.raises(PhotoSessionExpired):
        _commit(db, user, [img], [
            PhotoSelection(session_id=out.session_id, selected_region_ids=[0]),
        ])
    # Nothing was staged and no run was created for the failed request.
    assert db.query(IngestCandidate).count() == 0
    assert db.query(IngestRun).count() == 0


def test_commit_foreign_or_unknown_session_not_found(db, user):
    img = _sanitized()
    out = _detect_one(db, user, img, _two_garment_detection())

    other = User(email="o@example.com", hashed_password="x", display_name="O")
    db.add(other); db.commit(); db.refresh(other)

    # Another user's JWT cannot see this session (indistinguishable from absent).
    with pytest.raises(PhotoSessionNotFound):
        ingest_service.run_photo_commit(
            db, other.id, None, {img.sha256: img},
            [PhotoSelection(session_id=out.session_id, selected_region_ids=[0])],
        )
    # Unknown / non-UUID ids are equally absent.
    with pytest.raises(PhotoSessionNotFound):
        _commit(db, user, [img], [PhotoSelection(
            session_id="11111111-2222-3333-4444-555555555555",
            selected_region_ids=[0])])
    with pytest.raises(PhotoSessionNotFound):
        _commit(db, user, [img], [PhotoSelection(
            session_id="not-a-uuid", selected_region_ids=[0])])
    assert db.query(PhotoDetectSession).one().status == "pending"


def test_commit_missing_or_mismatched_file_conflicts(db, user):
    img = _sanitized()
    out = _detect_one(db, user, img, _two_garment_detection())
    wrong = _banded()  # a different photo than the session's sha256
    with pytest.raises(PhotoSessionConflict):
        _commit(db, user, [wrong], [
            PhotoSelection(session_id=out.session_id, selected_region_ids=[0]),
        ])
    assert db.query(IngestCandidate).count() == 0


def test_commit_invalid_region_ids_rejected(db, user):
    img = _sanitized()
    out = _detect_one(db, user, img, _two_garment_detection())
    with pytest.raises(PhotoSelectionInvalid):
        _commit(db, user, [img], [
            PhotoSelection(session_id=out.session_id, selected_region_ids=[0, 7]),
        ])
    assert db.query(IngestCandidate).count() == 0


@pytest.mark.parametrize("bad_box", [
    [50, 50, 500],                 # wrong arity
    [500, 50, 100, 600],           # ymin >= ymax
    [50, 500, 600, 100],           # xmin >= xmax
    [0, 0, 1001, 500],             # out of range
    [-1, 0, 500, 500],             # negative
    [0.5, 0, 500, 500],            # non-int
])
def test_commit_invalid_manual_box_rejected(db, user, bad_box):
    img = _sanitized()
    out = _detect_one(db, user, img, _two_garment_detection())
    with pytest.raises(PhotoSelectionInvalid):
        _commit(db, user, [img], [
            PhotoSelection(session_id=out.session_id, manual_boxes=[bad_box]),
        ])


def test_commit_too_many_manual_boxes_rejected(db, user):
    img = _sanitized()
    out = _detect_one(db, user, img, _two_garment_detection())
    boxes = [[0, 0, 100 + i, 100 + i] for i in range(9)]  # cap is 8
    with pytest.raises(PhotoSelectionInvalid):
        _commit(db, user, [img], [
            PhotoSelection(session_id=out.session_id, manual_boxes=boxes),
        ])


def test_commit_manual_box_describes_and_stages(db, user):
    img = _sanitized()
    out = _detect_one(db, user, img, _two_garment_detection())

    describe_calls = []
    def _describe(data, content_type, *, provider=None, usage=None):
        describe_calls.append((len(data), content_type))
        return GarmentDescription(
            name="Black Boot", category="shoes", color="black",
            confidence_overall=0.7,
        )

    box = [100, 100, 600, 600]
    res = _commit(db, user, [img], [
        PhotoSelection(session_id=out.session_id, manual_boxes=[box]),
    ], describe=_describe)

    assert res.staged == 1
    assert len(describe_calls) == 1
    assert describe_calls[0][1] == "image/jpeg"  # the CUTOUT bytes, not the photo

    cand = db.query(IngestCandidate).one()
    assert cand.name == "Black Boot"
    assert cand.category == "shoes"
    assert cand.color == "black"
    # Manual boxes use the SAME source_line_key scheme as detected regions.
    assert cand.source_line_key == _source_line_key(img.sha256, box)
    assert db.query(ProcessedUpload).one().item_count == 1


def test_commit_manual_box_describe_failure_stages_placeholder(db, user):
    img = _sanitized()
    out = _detect_one(db, user, img, _two_garment_detection())
    res = _commit(db, user, [img], [
        PhotoSelection(session_id=out.session_id, manual_boxes=[[100, 100, 600, 600]]),
    ], describe=lambda data, ct, *, provider=None, usage=None: None)

    assert res.staged == 1
    cand = db.query(IngestCandidate).one()
    assert cand.name == "Item"
    assert cand.category == "other"
    assert float(cand.confidence_overall) <= 0.3  # low confidence, editable in deck


def test_commit_zero_selection_leaves_photo_redetectable(db, user):
    img = _sanitized()
    out = _detect_one(db, user, img, _two_garment_detection())
    res = _commit(db, user, [img], [
        PhotoSelection(session_id=out.session_id),  # nothing selected
    ])
    assert res.staged == 0 and res.duplicates == 0
    assert db.query(IngestCandidate).count() == 0
    # No ledger row -> the photo can be re-detected later.
    assert db.query(ProcessedUpload).count() == 0
    assert db.query(PhotoDetectSession).one().status == "committed"

    # And a fresh detect on the same bytes is NOT a duplicate.
    out2 = _detect_one(db, user, img, _two_garment_detection())
    assert out2.duplicate is False and out2.session_id != out.session_id


def test_commit_recheck_counts_duplicate_and_retires_session(db, user):
    img = _sanitized()
    out = _detect_one(db, user, img, _two_garment_detection())
    # The same photo got committed by another request between detect and commit.
    db.add(ProcessedUpload(
        user_id=user.id, sync_id=None, image_sha256=img.sha256, phash=img.phash,
        status="processed", item_count=1,
    ))
    db.commit()

    res = _commit(db, user, [img], [
        PhotoSelection(session_id=out.session_id, selected_region_ids=[0]),
    ])
    assert res.duplicates == 1
    assert res.staged == 0 and res.images_processed == 0
    assert db.query(IngestCandidate).count() == 0
    assert db.query(PhotoDetectSession).one().status == "committed"


def test_commit_identical_boxes_collapse_to_one_candidate(db, user):
    img = _sanitized()
    detection = DetectionResult(person_count=1, garments=[
        _garment("A", box=(10, 10, 900, 900)),
        _garment("B", box=(10, 10, 900, 900)),
    ])
    out = _detect_one(db, user, img, detection)
    res = _commit(db, user, [img], [
        PhotoSelection(session_id=out.session_id, selected_region_ids=[0, 1]),
    ])
    # Same region -> same source_line_key -> ONE candidate row (staged counts both).
    assert db.query(IngestCandidate).count() == 1
    assert res.staged == 2


def test_commit_unusable_box_skipped(db, user):
    img = _sanitized()
    detection = DetectionResult(person_count=1, garments=[
        _garment("Good", box=(0, 0, 1000, 1000)),
        _garment("Bad", box=(0, 0, 1, 1)),  # sub-2px crop -> skipped by build_cutout
    ])
    out = _detect_one(db, user, img, detection)
    res = _commit(db, user, [img], [
        PhotoSelection(session_id=out.session_id, selected_region_ids=[0, 1]),
    ])
    assert res.staged == 1
    assert db.query(IngestCandidate).count() == 1


def test_commit_duplicate_sessions_in_selections_rejected(db, user):
    img = _sanitized()
    out = _detect_one(db, user, img, _two_garment_detection())
    with pytest.raises(PhotoSelectionInvalid):
        _commit(db, user, [img], [
            PhotoSelection(session_id=out.session_id, selected_region_ids=[0]),
            PhotoSelection(session_id=out.session_id, selected_region_ids=[1]),
        ])


def test_deck_scoped_to_current_run(db, user):
    """The deck fetch filters to the active sync_id AND to pending, so a photo run
    never surfaces stale candidates from a prior run."""
    from uuid import uuid4
    from app.gmail_closet.review_service import list_pending_candidates

    run_a, run_b = uuid4(), uuid4()

    def _cand(sync_id, slk, status="pending"):
        db.add(IngestCandidate(
            user_id=user.id, sync_id=sync_id, source_line_key=slk, name="x",
            category="top", status=status, source_type="photo",
            image_url="https://blob/x.jpg", image_status="user_uploaded",
        ))

    # run A: 2 pending. run B (older): 2 pending + 1 already accepted.
    _cand(run_a, "a1"); _cand(run_a, "a2")
    _cand(run_b, "b1"); _cand(run_b, "b2"); _cand(run_b, "b3", status="accepted")
    db.commit()

    scoped_a = list_pending_candidates(db, user.id, sync_id=str(run_a))
    assert len(scoped_a) == 2  # only run A's pending

    scoped_b = list_pending_candidates(db, user.id, sync_id=str(run_b))
    assert len(scoped_b) == 2  # run B's pending; the accepted one is excluded

    # Unscoped (Gmail deck behavior) is unchanged: all pending, accepted excluded.
    unscoped = list_pending_candidates(db, user.id)
    assert len(unscoped) == 4
