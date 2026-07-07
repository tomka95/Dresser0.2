"""Tests for Supabase Auth JWT verification and the (Supabase-only) auth dependency.

The shared harness — tests/_authutil.py plus the autouse ``_supabase_auth_env``
fixture in conftest.py — builds a throwaway EC P-256 keypair, publishes its public
half as a stubbed JWKS (no network), and mints Supabase-style ES256 tokens with the
private half. These tests assert that:
  * valid Supabase tokens verify and resolve/auto-provision a profile,
  * invalid issuer / audience / expiry / signature / kid are rejected.

Legacy HS256/custom-token acceptance was RETIRED; its rejection is proven in
tests/test_auth_hardening.py.

Runs under the SQLite test DB (see tests/conftest.py) -- no remote DB, no FK to
auth.users (that FK is Postgres/migration-only).
"""

import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

import app.supabase_auth as sa
from app.db import Base, SessionLocal, engine
from app.models import User
from main import app
from tests._authutil import TEST_ISSUER, mint_supabase_token


def _foreign_pem() -> str:
    """A PEM for a DIFFERENT EC key than the one published in the stubbed JWKS."""
    return (
        ec.generate_private_key(ec.SECP256R1())
        .private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        .decode()
    )


# --------------------------------------------------------------------------- #
# Pure verification
# --------------------------------------------------------------------------- #
def test_verify_valid_token_returns_claims():
    sub = str(uuid.uuid4())
    token = mint_supabase_token(sub=sub, email="a@b.com")
    claims = sa.verify_supabase_token(token)
    assert claims["sub"] == sub
    assert claims["email"] == "a@b.com"


def test_verify_rejects_wrong_issuer():
    token = mint_supabase_token(iss="https://evil.example.com/auth/v1")
    with pytest.raises(sa.SupabaseAuthError):
        sa.verify_supabase_token(token)


def test_verify_rejects_wrong_audience():
    token = mint_supabase_token(aud="some-other-aud")
    with pytest.raises(sa.SupabaseAuthError):
        sa.verify_supabase_token(token)


def test_verify_rejects_expired():
    token = mint_supabase_token(exp_delta=-10)
    with pytest.raises(sa.SupabaseAuthError):
        sa.verify_supabase_token(token)


def test_verify_rejects_bad_signature():
    # Signed with a different key than the one published in the JWKS.
    token = mint_supabase_token(key=_foreign_pem())
    with pytest.raises(sa.SupabaseAuthError):
        sa.verify_supabase_token(token)


def test_verify_rejects_unknown_kid():
    token = mint_supabase_token(kid="nonexistent-kid")
    with pytest.raises(sa.SupabaseAuthError):
        sa.verify_supabase_token(token)


# --------------------------------------------------------------------------- #
# Dependency via the live /auth/me endpoint
# --------------------------------------------------------------------------- #
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


def test_supabase_token_auto_provisions_profile(db, client):
    sub = str(uuid.uuid4())
    token = mint_supabase_token(
        sub=sub, email="new@example.com",
        metadata={"full_name": "New User", "avatar_url": "http://img/x.png"},
    )
    assert db.query(User).filter(User.id == uuid.UUID(sub)).first() is None

    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == sub
    assert body["email"] == "new@example.com"
    assert body["full_name"] == "New User"

    # Provisioned exactly once; a second call resolves the same row.
    resp2 = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp2.status_code == 200
    db.expire_all()
    assert db.query(User).filter(User.email == "new@example.com").count() == 1


def test_supabase_token_resolves_existing_profile(db, client):
    sub = uuid.uuid4()
    db.add(User(id=sub, email="existing@example.com", hashed_password="",
                full_name="Existing"))
    db.commit()

    token = mint_supabase_token(sub=str(sub), email="existing@example.com")
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == str(sub)
    db.expire_all()
    assert db.query(User).filter(User.email == "existing@example.com").count() == 1


def test_garbage_token_is_rejected(db, client):
    resp = client.get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert resp.status_code == 401
