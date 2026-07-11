"""Account deletion + GDPR export (DELETE /account, GET /account/export).

Covers the contract the App Store 5.1.1 / GDPR feature must hold:
  * a full delete leaves ZERO rows across every user-owning table for that user;
  * a second delete call is idempotent (still 200, still zero);
  * the export excludes all token material;
  * the typed confirmation is required (400 without it);
  * deletion is JWT-pinned — another user's data is untouched;
  * shared product-catalog rows (product_image_cache / image_blobs) are preserved;
  * the storage prefix-sweep deletes only the user's own key prefix.

External side effects (Google revoke, GoTrue admin delete, S3) are neutralised so
the suite never makes a live call — the DB erasure is exercised for real.
"""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.services.account_deletion as account_deletion
from app.db import Base, SessionLocal, engine
from app.models import (
    CalendarAccount,
    ChatMessage,
    ChatRateWindow,
    ChatUsage,
    ClothingItem,
    Conversation,
    GoogleAccount,
    ImageBlob,
    ItemImage,
    Job,
    PhotoUsage,
    PreferenceSignal,
    ProcessedMessage,
    ProductClick,
    ProductImageCache,
    SavedOutfit,
    StyleEvent,
    StylePreference,
    StyleProfile,
    TodaysLookCache,
    User,
)
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


@pytest.fixture(autouse=True)
def _no_external_calls(monkeypatch):
    """No live Google revoke / GoTrue admin / S3 calls from the deletion path."""
    from app.core.config import settings

    # GoTrue admin delete short-circuits (no identity to delete in local mode).
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", None, raising=False)

    class _FakeHttpx:
        @staticmethod
        def post(*a, **k):
            return None

        @staticmethod
        def delete(*a, **k):
            class _R:
                status_code = 204

            return _R()

    monkeypatch.setattr(account_deletion, "httpx", _FakeHttpx)
    # Storage sweep is unit-tested separately; neutralise it here.
    monkeypatch.setattr(account_deletion, "delete_user_storage_objects", lambda uid: 0)
    yield


def _auth(user: User) -> dict:
    token = mint_supabase_token(sub=str(user.id), email=user.email)
    return {"Authorization": f"Bearer {token}"}


def _make_user(db: Session, email: str) -> User:
    u = User(id=uuid.uuid4(), email=email, hashed_password="")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _populate(db: Session, user: User, *, with_image: bool) -> None:
    """Insert one row into a broad set of the user's tables (parents + children)."""
    item = ClothingItem(user_id=user.id, name="Blue Tee", category="top")
    db.add(item)
    db.flush()
    if with_image:
        db.add(ItemImage(clothing_item_id=item.id, image_url="https://x/y.png"))

    conv = Conversation(user_id=user.id, title="chat")
    db.add(conv)
    db.flush()
    db.add(
        ChatMessage(conversation_id=conv.id, user_id=user.id, role="user", content="hi")
    )

    db.add(StyleProfile(user_id=user.id, facts={"sizes": {"top": "M"}}, narrative_blob={}, summary="s"))
    db.add(StylePreference(user_id=user.id, dimension="color", value={"like": ["navy"]}, source="explicit"))
    db.add(SavedOutfit(user_id=user.id, item_ids=[str(item.id)], source="chat"))
    db.add(StyleEvent(user_id=user.id, event_type="item_view", item_id=item.id))
    db.add(PreferenceSignal(user_id=user.id, signal_type="behavior"))
    db.add(ChatUsage(user_id=user.id, period_start=datetime.now(timezone.utc).date()))
    db.add(ChatRateWindow(user_id=user.id, window_start=datetime.now(timezone.utc), count=1))
    # GoogleAccount.id is BigInteger (no SQLite autoincrement) — assign explicitly.
    gid = (db.query(GoogleAccount).count() or 0) + 1
    db.add(GoogleAccount(id=gid, user_id=user.id, access_token="ENC_GMAIL_ACCESS", refresh_token="ENC_GMAIL_REFRESH"))
    db.add(CalendarAccount(user_id=user.id, access_token="ENC_CAL_ACCESS", refresh_token="ENC_CAL_REFRESH"))
    db.add(Job(type="gmail_ingest", user_id=user.id, payload={}))
    db.add(PhotoUsage(user_id=user.id, period_start=datetime.now(timezone.utc).date()))
    db.add(ProcessedMessage(user_id=user.id, message_id="m1"))
    db.add(ProductClick(user_id=user.id, surface="feed"))
    db.add(
        TodaysLookCache(
            user_id=user.id,
            factor_signature="sig",
            outfit_json={},
            half_day_bucket="2026-07-11:AM",
        )
    )
    db.commit()


# All user-owning tables (from the deletion order) plus users itself.
_USER_MODELS = list(account_deletion._USER_TABLE_DELETE_ORDER) + [User]


def _user_row_counts(db: Session, user_id) -> dict:
    counts = {}
    for model in account_deletion._USER_TABLE_DELETE_ORDER:
        counts[model.__tablename__] = (
            db.query(model).filter(model.user_id == user_id).count()
        )
    counts["users"] = db.query(User).filter(User.id == user_id).count()
    return counts


def test_full_delete_leaves_zero_user_rows(db, client):
    user = _make_user(db, "erase@example.com")
    other = _make_user(db, "keep@example.com")
    _populate(db, user, with_image=True)
    _populate(db, other, with_image=False)

    # A shared product-catalog row (NOT user data) — must survive deletion.
    db.add(ImageBlob(content_sha256="a" * 64, image_url="https://cdn/blob.png"))
    db.add(ProductImageCache(cache_key="brand|tee|navy", image_url="https://cdn/p.png"))
    db.commit()

    # Capture ids/headers before deletion (the ORM objects go stale once the
    # endpoint's own session deletes the rows).
    uid, other_uid, hdr = user.id, other.id, _auth(user)

    # Sanity: the target user has data before deletion.
    before = _user_row_counts(db, uid)
    assert before["clothing_items"] == 1 and before["users"] == 1

    resp = client.request("DELETE", "/account", json={"confirmation": "DELETE"}, headers=hdr)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": True}

    db.expire_all()

    # PROOF OF ZERO ROWS: every user-owning table has 0 rows for this user.
    after = _user_row_counts(db, uid)
    assert after == {name: 0 for name in after}, after

    # item_images (no user_id) — none of the deleted user's item images remain.
    assert db.query(ItemImage).count() == 0

    # JWT-pinned: the other user's data is fully intact.
    assert db.query(ClothingItem).filter(ClothingItem.user_id == other_uid).count() == 1
    assert db.query(User).filter(User.id == other_uid).count() == 1

    # Shared product-catalog rows preserved.
    assert db.query(ImageBlob).count() == 1
    assert db.query(ProductImageCache).count() == 1


def test_second_delete_is_idempotent(db, client):
    user = _make_user(db, "again@example.com")
    _populate(db, user, with_image=True)
    uid, hdr = user.id, _auth(user)

    first = client.request("DELETE", "/account", json={"confirmation": "DELETE"}, headers=hdr)
    assert first.status_code == 200

    # The token is still valid; a retry must not error. get_current_user re-provisions
    # a bare profile from the JWT, which the delete then removes again → still zero.
    second = client.request("DELETE", "/account", json={"confirmation": "DELETE"}, headers=hdr)
    assert second.status_code == 200, second.text

    db.expire_all()
    final = _user_row_counts(db, uid)
    assert final == {name: 0 for name in final}


def test_confirmation_required(db, client):
    user = _make_user(db, "typo@example.com")
    _populate(db, user, with_image=False)

    resp = client.request("DELETE", "/account", json={"confirmation": "delete please"}, headers=_auth(user))
    assert resp.status_code == 400

    # Nothing was deleted.
    db.expire_all()
    assert db.query(User).filter(User.id == user.id).count() == 1
    assert db.query(ClothingItem).filter(ClothingItem.user_id == user.id).count() == 1


def test_delete_requires_auth(db, client):
    resp = client.request("DELETE", "/account", json={"confirmation": "DELETE"})
    assert resp.status_code in (401, 403)


def test_export_excludes_tokens_and_includes_data(db, client):
    user = _make_user(db, "export@example.com")
    _populate(db, user, with_image=True)

    resp = client.get("/account/export", headers=_auth(user))
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].endswith('filename="tailor-data-export.json"')

    raw = resp.text
    # No token material of any kind leaks into the export.
    for secret in ("ENC_GMAIL_ACCESS", "ENC_GMAIL_REFRESH", "ENC_CAL_ACCESS", "ENC_CAL_REFRESH"):
        assert secret not in raw
    assert "access_token" not in raw and "refresh_token" not in raw
    assert "hashed_password" not in raw

    body = resp.json()
    # Real user data IS present, human-readably.
    assert body["account"]["email"] == "export@example.com"
    assert body["account"]["connections"]["gmail_connected"] is True
    assert body["account"]["connections"]["calendar_connected"] is True
    assert body["counts"]["closet_items"] == 1
    assert body["closet_items"][0]["name"] == "Blue Tee"
    assert body["style_profile"]["facts"] == {"sizes": {"top": "M"}}
    assert len(body["saved_outfits"]) == 1


def test_export_requires_auth(db, client):
    resp = client.get("/account/export")
    assert resp.status_code in (401, 403)


# --- Storage prefix sweep (unit) ---------------------------------------------


def test_storage_delete_prefix_sweeps_only_user_prefix(monkeypatch):
    from app.utils.supabase_storage import SupabaseStorageClient

    deleted_keys = []

    class _FakePaginator:
        def paginate(self, Bucket, Prefix):
            assert Prefix == "user-123/"
            yield {"Contents": [{"Key": "user-123/a.png"}, {"Key": "user-123/b.png"}]}
            yield {"Contents": [{"Key": "user-123/c.png"}]}

    class _FakeS3:
        def get_paginator(self, name):
            assert name == "list_objects_v2"
            return _FakePaginator()

        def delete_objects(self, Bucket, Delete):
            deleted_keys.extend(o["Key"] for o in Delete["Objects"])

    client = SupabaseStorageClient.__new__(SupabaseStorageClient)
    client.bucket = "Clothing_Items_Images"
    client.public_base_url = "https://x/object/public"
    client.s3 = _FakeS3()

    n = client.delete_prefix("user-123/")
    assert n == 3
    assert deleted_keys == ["user-123/a.png", "user-123/b.png", "user-123/c.png"]

    # Refuses an empty / bucket-wide prefix — can never wipe the whole bucket.
    assert client.delete_prefix("") == 0
    assert client.delete_prefix("no-slash") == 0
