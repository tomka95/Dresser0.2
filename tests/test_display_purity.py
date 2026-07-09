"""Photo-seam Phase 5 — display purity + the raw-crop purge lifecycle.

Gates:
  * THE display gate is generated-card-only for photo/manual sources: every backend
    surface (closet API, stylist retrieval, composer payloads, collages, deck) emits
    the verified card or None (neutral placeholder) — never a raw crop, never a
    person, never for a failed item.
  * RAW-CROP PURGE: the moment a verified card lands (_stamp_candidate_card_ready),
    the candidate's crop pointer is nulled (display-unreachable) and our own
    photo_items/ blob (+ its image_blobs dedup row) is deleted best-effort. Foreign/
    shared references are unlinked, never deleted.
  * delete_object parses ONLY our public-URL shape; foreign URLs are refused.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, engine
from app.models import IngestCandidate, IngestRun, User
from app.models.closet import ClothingItem, display_image_url
from app.photo_closet import generation_service as gen
from app.services.image_generation.generate_core import GenOutcome
from app.services.stylist.collage import usable_image_url


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
    u = User(email="purity@example.com", hashed_password="x", display_name="P")
    db.add(u); db.commit(); db.refresh(u)
    return u


CROP = "https://cdn.example/storage/v1/object/public/bucket/photo_items/u1/crop.jpg"


def _cand(db, user, sync, **over):
    fields = dict(
        user_id=user.id, sync_id=sync, source_type="photo", status="pending",
        source_line_key=f"k-{uuid.uuid4().hex[:8]}",
        image_url=CROP, image_status="user_uploaded",
        name="Crew Tee", category="top", color="red", size="M",
        pipeline_state="staged", person_status="person_present", on_model=True,
    )
    fields.update(over)
    c = IngestCandidate(**fields)
    db.add(c); db.commit(); db.refresh(c)
    return c


class _FakeStorage:
    def __init__(self):
        self.deleted = []

    def delete_object(self, url):
        self.deleted.append(url)
        return True


# ===========================================================================
# The display gate — generated-card-only matrix (photo/manual vs gmail)
# ===========================================================================

def _item(**over):
    base = dict(
        source_type="photo", image_url=CROP, person_status="person_free",
        generation_status="pending_retry",
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_display_gate_matrix():
    # photo/manual: card ONLY when generation_status == 'ready'.
    assert display_image_url(_item(generation_status="ready", image_url="card")) == "card"
    for status in ("pending_retry", "generating", "failed", None):
        assert display_image_url(_item(generation_status=status)) is None
    assert display_image_url(_item(source_type="manual", generation_status=None)) is None
    assert display_image_url(
        _item(source_type="manual", generation_status="ready", image_url="card")
    ) == "card"
    # failed items never appear on user surfaces.
    assert display_image_url(_item(generation_status="failed", image_url=CROP)) is None
    # gmail: affirmative person_free shows the verified resolved image; unknown masks.
    assert display_image_url(
        _item(source_type="gmail", generation_status=None, image_url="retailer")
    ) == "retailer"
    assert display_image_url(
        _item(source_type="gmail", generation_status=None,
              person_status="unknown", image_url="retailer")
    ) is None


def test_collage_usable_follows_the_gate():
    # A person-free photo crop mid-retry is NOT usable in any collage anymore.
    assert usable_image_url(_item(image_status="user_uploaded")) is None
    assert usable_image_url(
        _item(generation_status="ready", image_url="card", image_status="user_uploaded")
    ) == "card"


# ===========================================================================
# Raw-crop purge at the card stamp
# ===========================================================================

def test_stamp_purges_photo_crop_and_blob(db, user, monkeypatch):
    sync = uuid4()
    c = _cand(db, user, sync)
    storage = _FakeStorage()
    blob_deleted = []
    import app.utils.image_blob_store as blob_store
    monkeypatch.setattr(blob_store, "delete_by_url", lambda url: blob_deleted.append(url) or 1)

    gen._stamp_candidate_card_ready(db, c, "https://cdn/card.png", storage_client=storage)
    db.commit()

    assert c.generated_image_url == "https://cdn/card.png"
    assert c.pipeline_state == "ready" and c.person_status == "person_free"
    assert c.image_url is None                      # display-unreachable, always
    assert storage.deleted == [CROP]                # our photo_items/ blob deleted
    assert blob_deleted == [CROP]                   # dedup row dropped too


def test_stamp_unlinks_but_never_deletes_foreign_reference(db, user, monkeypatch):
    """A manual add's uploaded reference (regenerate_refs/, or any non-photo_items
    URL) is unlinked only — the content-addressed blob store shares identical bytes
    across rows, so deleting could break another reference."""
    ref = "https://cdn.example/storage/v1/object/public/bucket/regenerate_refs/u1/ref.jpg"
    sync = uuid4()
    c = _cand(db, user, sync, source_type="manual", image_url=ref,
              person_status="unknown", on_model=False)
    storage = _FakeStorage()
    import app.utils.image_blob_store as blob_store
    monkeypatch.setattr(blob_store, "delete_by_url",
                        lambda url: pytest.fail("must not touch the blob mapping"))

    gen._stamp_candidate_card_ready(db, c, "https://cdn/card.png", storage_client=storage)
    db.commit()

    assert c.image_url is None
    assert storage.deleted == []                    # unlink only, never delete


def test_purged_candidate_payload_carries_no_crop_url(db, user, monkeypatch):
    """Post-purge, no display query can resolve to the raw crop: the deck payload for
    the ready candidate contains the card and nothing else."""
    from app.gmail_closet.review_service import _candidate_to_view

    sync = uuid4()
    c = _cand(db, user, sync)
    gen._stamp_candidate_card_ready(db, c, "https://cdn/card.png", storage_client=None)
    db.commit()

    view = _candidate_to_view(c, None)
    assert view["generated_image_url"] == "https://cdn/card.png"
    assert view["image_url"] is None
    assert CROP not in str(view)                    # the crop URL appears NOWHERE


def test_worker_ready_path_purges_via_stamp(db, user, monkeypatch):
    """End-to-end through run_photo_generation: the ready path nulls the crop."""
    sync = uuid4()
    db.add(IngestRun(sync_id=sync, user_id=user.id, status="running", source_type="photo"))
    db.commit()
    c = _cand(db, user, sync, person_status="person_free", on_model=False)

    monkeypatch.setattr(gen, "_download_bytes", lambda url: (b"cut", "image/jpeg"))
    monkeypatch.setattr(
        gen, "generate_from_reference_bytes",
        lambda **kw: GenOutcome("ready", url="https://blob/card.png",
                                content_sha256="aa" * 32, verify_score=0.9),
    )
    storage = _FakeStorage()
    import app.utils.image_blob_store as blob_store
    monkeypatch.setattr(blob_store, "delete_by_url", lambda url: 1)

    stats = gen.run_photo_generation(user.id, db, sync, storage_client=storage)

    db.refresh(c)
    assert stats.ready == 1
    assert c.image_url is None
    assert storage.deleted == [CROP]


# ===========================================================================
# delete_object URL-shape safety
# ===========================================================================

def test_delete_object_parses_only_our_shape(monkeypatch):
    from app.utils.supabase_storage import SupabaseStorageClient

    client = SupabaseStorageClient.__new__(SupabaseStorageClient)  # skip boto init
    client.bucket = "bucket"
    client.public_base_url = "https://cdn.example/storage/v1/object/public"
    calls = []
    client.s3 = SimpleNamespace(
        delete_object=lambda Bucket, Key: calls.append((Bucket, Key))
    )

    ok = client.delete_object(
        "https://cdn.example/storage/v1/object/public/bucket/photo_items/u1/x.jpg"
    )
    assert ok is True
    assert calls == [("bucket", "photo_items/u1/x.jpg")]

    # Foreign URLs and implausible keys are refused — never deleted.
    assert client.delete_object("https://evil.example/bucket/photo_items/u1/x.jpg") is False
    assert client.delete_object("x.jpg") is False
    assert client.delete_object("") is False
    assert calls == [("bucket", "photo_items/u1/x.jpg")]
