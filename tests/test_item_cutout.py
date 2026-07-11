"""Collage Phase 1 — the item-cutout seam (matte once at birth).

Gates:
  * the QA gate accepts a clean single-blob matte and refuses each spike-observed
    failure shape (empty / full-frame / border-running / fragmented / sub-object
    vs the key estimate) — a refused matte is 'no_matte', NEVER a rectangle;
  * matte_item is fail-open on transient trouble ('skipped', row stays NULL — a
    backfill target) and fail-closed on QA ('no_matte', terminal until retried);
  * the matte source is THE display gate: a masked item is never matted;
  * the birth hook stamps newborn items and is idempotent on re-confirm;
  * the backfill selects only never-matted rows (idempotent, resumable,
    --retry-no-matte reselects refusals), and dry-run writes NOTHING;
  * static: both confirm-chokepoint callers schedule the hook.

No test loads the model: the engine seam (service.matte_rgba) is monkeypatched.
"""
from __future__ import annotations

import io
import uuid

import numpy as np
import pytest
from PIL import Image
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import Base, SessionLocal, engine
from app.models import ClothingItem, User
from app.services.item_cutout import service
from app.services.item_cutout.qa import qa_matte


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
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
    u = User(email="cutout@example.com", hashed_password="x", display_name="C")
    db.add(u); db.commit(); db.refresh(u)
    return u


def _displayable_item(db, user, **over) -> ClothingItem:
    """A gmail item the display gate shows (person_free + resolved image)."""
    vals = dict(
        user_id=user.id,
        name="White tee",
        category="top",
        source_type="gmail",
        person_status="person_free",
        image_status="resolved",
        image_url="https://cdn.example/storage/card.jpg",
    )
    vals.update(over)
    item = ClothingItem(**vals)
    db.add(item); db.commit(); db.refresh(item)
    return item


# ---------------------------------------------------------------------------
# synthetic mattes: a "product shot" 320x320 with a centered dark garment
# ---------------------------------------------------------------------------
W = H = 320
BG = (240, 238, 232)
GARMENT = (60, 60, 90)
GX0, GY0, GX1, GY1 = 80, 60, 240, 260  # 160x200 centered, clean margins


def _shot_rgb() -> np.ndarray:
    a = np.zeros((H, W, 3), np.uint8)
    a[:, :] = BG
    a[GY0:GY1, GX0:GX1] = GARMENT
    return a


def _rgba(alpha: np.ndarray) -> Image.Image:
    return Image.fromarray(np.dstack([_shot_rgb(), alpha]))


def _good_alpha() -> np.ndarray:
    al = np.zeros((H, W), np.uint8)
    al[GY0:GY1, GX0:GX1] = 255
    return al


def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.fromarray(_shot_rgb()).save(buf, format="JPEG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# QA gate
# ---------------------------------------------------------------------------
def test_qa_accepts_clean_single_blob_matte():
    v = qa_matte(_rgba(_good_alpha()))
    assert v.ok and v.reason == "ok"


def test_qa_refuses_empty_and_full_frame():
    assert qa_matte(_rgba(np.zeros((H, W), np.uint8))).reason == "empty_matte"
    assert qa_matte(_rgba(np.full((H, W), 255, np.uint8))).reason == "full_frame_matte"


def test_qa_refuses_border_running_matte():
    al = _good_alpha()
    al[:, :40] = 255  # matte runs off the left edge — model found no bounded object
    assert qa_matte(_rgba(al)).reason == "border_contact"


def test_qa_refuses_fragmented_matte():
    # Three separated blobs; the largest carries only ~66% of the opaque area.
    al = np.zeros((H, W), np.uint8)
    al[60:160, 40:140] = 255    # 100x100
    al[200:260, 200:260] = 255  # 60x60
    al[40:80, 240:280] = 255    # 40x40
    assert qa_matte(_rgba(al)).reason == "fragmented_matte"


def test_qa_refuses_sub_object_matte_via_key_cross_check():
    # The isnet-on-white-tee failure shape: alpha keeps only a small graphic while
    # the key estimate says the garment is much larger.
    al = np.zeros((H, W), np.uint8)
    al[140:220, 130:190] = 255  # 60x80 patch inside the 160x200 garment
    assert qa_matte(_rgba(al)).reason == "undersized_vs_key"


def test_qa_never_raises_on_garbage():
    v = qa_matte(Image.new("L", (4, 4)))  # wrong-mode, degenerate input
    assert not v.ok  # fail-closed, whatever the reason


# ---------------------------------------------------------------------------
# matte_item — dispositions
# ---------------------------------------------------------------------------
@pytest.fixture
def seams(monkeypatch):
    """Happy-path seams: download works, engine mattes cleanly, storage stores."""
    monkeypatch.setattr(service, "_download", lambda url: (_jpeg_bytes(), "image/jpeg"))
    monkeypatch.setattr(service, "matte_rgba", lambda img: _rgba(_good_alpha()))
    monkeypatch.setattr(
        service, "_store_cutout",
        lambda user_id, png: "https://cdn.example/storage/item_cutouts/u/c.png",
    )


def test_matte_item_happy_path_stamps_ready(db, user, seams):
    item = _displayable_item(db, user)
    assert service.matte_item(db, item) == "ready"
    db.commit()
    assert item.cutout_status == "ready"
    assert item.cutout_url == "https://cdn.example/storage/item_cutouts/u/c.png"


def test_matte_item_qa_refusal_is_no_matte_never_rectangle(db, user, seams, monkeypatch):
    # Engine returns a border-running matte -> QA refuses -> terminal 'no_matte',
    # cutout_url stays NULL. The item row itself is untouched otherwise (its birth
    # and its flat-tile render are unaffected).
    bad = _good_alpha(); bad[:, :40] = 255
    monkeypatch.setattr(service, "matte_rgba", lambda img: _rgba(bad))
    item = _displayable_item(db, user)
    assert service.matte_item(db, item) == "no_matte"
    assert item.cutout_status == "no_matte"
    assert item.cutout_url is None


def test_matte_item_masked_item_is_skipped_not_matted(db, user, seams, monkeypatch):
    # A photo item without a ready card is MASKED by the display gate — the matte
    # must not even download it (a person/raw crop never reaches the engine).
    monkeypatch.setattr(
        service, "_download",
        lambda url: pytest.fail("masked item must never be downloaded"),
    )
    item = _displayable_item(
        db, user, source_type="photo", generation_status="pending_retry",
        person_status="unknown", image_status=None,
    )
    assert service.matte_item(db, item) == "skipped"
    assert item.cutout_status is None and item.cutout_url is None


def test_matte_item_transient_failures_stay_null(db, user, seams, monkeypatch):
    item = _displayable_item(db, user)
    # engine unavailable -> skipped, still a backfill target
    monkeypatch.setattr(service, "matte_rgba", lambda img: None)
    assert service.matte_item(db, item) == "skipped"
    assert item.cutout_status is None
    # storage unavailable -> skipped too (retryable, not terminal)
    monkeypatch.setattr(service, "matte_rgba", lambda img: _rgba(_good_alpha()))
    monkeypatch.setattr(service, "_store_cutout", lambda user_id, png: None)
    assert service.matte_item(db, item) == "skipped"
    assert item.cutout_status is None


def test_matte_item_kill_switch(db, user, seams, monkeypatch):
    monkeypatch.setattr(settings, "CUTOUT_MATTING_ENABLED", False)
    item = _displayable_item(db, user)
    assert service.matte_item(db, item) == "skipped"
    assert item.cutout_status is None


# ---------------------------------------------------------------------------
# birth hook
# ---------------------------------------------------------------------------
def test_birth_hook_stamps_newborn_items_and_is_idempotent(db, user, seams):
    item = _displayable_item(db, user)
    service.matte_items_background(str(user.id), [str(item.id)])
    db.expire_all()
    assert item.cutout_status == "ready" and item.cutout_url

    # Re-confirm of an already-matted row: the hook must not re-matte (the engine
    # seam would blow up the test if called).
    import app.services.item_cutout.service as svc
    orig = svc.matte_rgba
    try:
        svc.matte_rgba = lambda img: pytest.fail("already-matted item re-matted")
        service.matte_items_background(str(user.id), [str(item.id)])
    finally:
        svc.matte_rgba = orig


def test_birth_hook_never_raises(db, user, monkeypatch):
    # Engine explodes -> hook logs and returns; items stay NULL (backfill target).
    monkeypatch.setattr(service, "_download", lambda url: (_jpeg_bytes(), "image/jpeg"))
    monkeypatch.setattr(
        service, "matte_rgba",
        lambda img: (_ for _ in ()).throw(RuntimeError("onnx exploded")),
    )
    item = _displayable_item(db, user)
    service.matte_items_background(str(user.id), [str(item.id)])  # must not raise
    db.expire_all()
    assert item.cutout_status is None


def test_confirm_chokepoint_callers_schedule_the_hook():
    """Static scan (repo precedent): every path through THE confirm chokepoint
    schedules the birth hook — the deck confirm route (gmail + photo + chat-added
    photos all confirm there) and the manual auto-confirm."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    route = (root / "app/api/routes/gmail_ingest.py").read_text()
    manual = (root / "app/photo_closet/generation_service.py").read_text()
    assert "matte_items_background" in route
    assert "matte_items_background" in manual


# ---------------------------------------------------------------------------
# backfill script
# ---------------------------------------------------------------------------
def _run_backfill(monkeypatch, argv):
    import scripts.backfill_cutouts as bf

    monkeypatch.setattr("sys.argv", ["backfill_cutouts"] + argv)
    return bf.main()


def test_backfill_dry_run_writes_nothing(db, user, seams, monkeypatch):
    item = _displayable_item(db, user)
    assert _run_backfill(monkeypatch, []) == 0
    db.expire_all()
    assert item.cutout_status is None and item.cutout_url is None


def test_backfill_apply_idempotent_and_retry_flag(db, user, seams, monkeypatch):
    ok_item = _displayable_item(db, user)
    refused = _displayable_item(db, user, name="Belt", category="accessory",
                                cutout_status="no_matte")

    assert _run_backfill(monkeypatch, ["--apply"]) == 0
    db.expire_all()
    assert ok_item.cutout_status == "ready"
    assert refused.cutout_status == "no_matte"  # not reselected without the flag

    # Idempotent: a second --apply run finds nothing to matte.
    monkeypatch.setattr(
        service, "matte_rgba", lambda img: pytest.fail("second run re-matted a row")
    )
    assert _run_backfill(monkeypatch, ["--apply"]) == 0

    # --retry-no-matte reselects the refusal (and this time it mattes cleanly).
    monkeypatch.setattr(service, "matte_rgba", lambda img: _rgba(_good_alpha()))
    assert _run_backfill(monkeypatch, ["--apply", "--retry-no-matte"]) == 0
    db.expire_all()
    assert refused.cutout_status == "ready"


def test_backfill_skips_archived_items(db, user, seams, monkeypatch):
    from datetime import datetime, timezone

    archived = _displayable_item(db, user, archived_at=datetime.now(timezone.utc))
    assert _run_backfill(monkeypatch, ["--apply"]) == 0
    db.expire_all()
    assert archived.cutout_status is None
