"""Gmail disconnect (SCRUM-51) — a verbatim mirror of the calendar disconnect.

POST /gmail/oauth/disconnect revokes the grant at Google, wipes the google_accounts
token row, and flips /auth/me's gmail_connected to false. It is idempotent, and it must
NOT delete already-ingested closet items or the processed_messages dedup ledger — keeping
that ledger is exactly what prevents a reconnect from re-importing duplicates.
"""
import base64
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import token_crypto
from app.db import Base, SessionLocal, engine
from app.models import ClothingItem, GoogleAccount, ProcessedMessage, User
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
    u = User(email="gm1@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture(autouse=True)
def _crypto(monkeypatch):
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(token_crypto.settings, "GMAIL_TOKEN_ENC_KEY", key)
    token_crypto._key.cache_clear()
    yield
    token_crypto._key.cache_clear()


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def _seed_connected(db, user, *, refresh="refresh-plain"):
    # BigInteger PK doesn't auto-populate on SQLite -> set it explicitly (as sibling tests do).
    from app.core.token_crypto import encrypt_token
    acct = GoogleAccount(
        id=1,
        user_id=user.id,
        email=user.email,
        access_token=encrypt_token("access-plain", field="access_token"),
        refresh_token=encrypt_token(refresh, field="refresh_token") if refresh else None,
        scope="https://www.googleapis.com/auth/gmail.readonly",
        token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(acct); db.commit(); db.refresh(acct)
    return acct


def test_disconnect_revokes_and_wipes(client, db, user1, monkeypatch):
    _seed_connected(db, user1)
    revoked = {"called": False}
    monkeypatch.setattr("app.api.routes.gmail_oauth.httpx.post",
                        lambda *a, **k: revoked.__setitem__("called", True))
    tok = mint_supabase_token(sub=str(user1.id))

    resp = client.post("/gmail/oauth/disconnect", headers=_auth(tok))
    assert resp.status_code == 200 and resp.json() == {"connected": False}
    assert revoked["called"] is True  # grant revoked at Google
    assert db.query(GoogleAccount).filter(GoogleAccount.user_id == user1.id).count() == 0

    # /auth/me now reports disconnected.
    me = client.get("/auth/me", headers=_auth(tok))
    assert me.status_code == 200 and me.json()["gmail_connected"] is False


def test_disconnect_is_idempotent(client, db, user1, monkeypatch):
    monkeypatch.setattr("app.api.routes.gmail_oauth.httpx.post", lambda *a, **k: None)
    tok = mint_supabase_token(sub=str(user1.id))

    # No account at all -> success, no error.
    assert client.post("/gmail/oauth/disconnect", headers=_auth(tok)).json() == {"connected": False}

    # With an account, disconnect twice -> both succeed, row gone after the first.
    _seed_connected(db, user1)
    assert client.post("/gmail/oauth/disconnect", headers=_auth(tok)).status_code == 200
    assert client.post("/gmail/oauth/disconnect", headers=_auth(tok)).status_code == 200
    assert db.query(GoogleAccount).filter(GoogleAccount.user_id == user1.id).count() == 0


def test_disconnect_survives_google_revoke_failure(client, db, user1, monkeypatch):
    # A Google-side revoke error must NOT strand the user with an un-deletable row.
    _seed_connected(db, user1)

    def _boom(*a, **k):
        raise RuntimeError("google down")

    monkeypatch.setattr("app.api.routes.gmail_oauth.httpx.post", _boom)
    tok = mint_supabase_token(sub=str(user1.id))
    resp = client.post("/gmail/oauth/disconnect", headers=_auth(tok))
    assert resp.status_code == 200
    assert db.query(GoogleAccount).filter(GoogleAccount.user_id == user1.id).count() == 0


def test_disconnect_preserves_items_and_ledger(client, db, user1, monkeypatch):
    # Disconnect wipes ONLY the token row. Ingested items + the processed_messages ledger
    # survive, so a reconnect skips every previously-seen message (no duplicate import).
    acct = _seed_connected(db, user1)
    db.add(ClothingItem(user_id=user1.id, name="Receipt Tee", category="top",
                        source_type="gmail"))
    db.add(ProcessedMessage(user_id=user1.id, google_account_id=acct.id,
                            message_id="msg-abc", status="fetched"))
    db.add(ProcessedMessage(user_id=user1.id, google_account_id=acct.id,
                            message_id="msg-def", status="extracted"))
    db.commit()

    monkeypatch.setattr("app.api.routes.gmail_oauth.httpx.post", lambda *a, **k: None)
    tok = mint_supabase_token(sub=str(user1.id))
    assert client.post("/gmail/oauth/disconnect", headers=_auth(tok)).status_code == 200

    assert db.query(GoogleAccount).filter(GoogleAccount.user_id == user1.id).count() == 0
    # Ledger + items untouched.
    assert db.query(ProcessedMessage).filter(ProcessedMessage.user_id == user1.id).count() == 2
    assert db.query(ClothingItem).filter(ClothingItem.user_id == user1.id).count() == 1


def test_disconnect_requires_auth(client):
    assert client.post("/gmail/oauth/disconnect").status_code in (401, 403)
