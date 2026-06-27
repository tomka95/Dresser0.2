"""Tests for Supabase Auth JWT verification and the dual-accept dependency.

These build a throwaway EC P-256 keypair, publish its public half as a fake JWKS
(no network), mint Supabase-style tokens with the private half, and assert that:
  * valid Supabase tokens verify and resolve/auto-provision a profile,
  * invalid issuer / audience / expiry / signature are rejected,
  * legacy custom JWTs still authenticate (dual-accept),
  * routing (looks_like_supabase_token) classifies tokens correctly.

Runs under the SQLite test DB (see tests/conftest.py) -- no remote DB, no FK to
auth.users (that FK is Postgres/migration-only).
"""

import time
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from jose import jwk, jwt
from jose.constants import ALGORITHMS

import app.supabase_auth as sa
from app.core.config import settings
from app.db import Base, SessionLocal, engine
from app.models import User
from app.security import create_access_token
from main import app

TEST_ISSUER_BASE = "https://test-project.supabase.co"
TEST_ISSUER = f"{TEST_ISSUER_BASE}/auth/v1"
TEST_KID = "test-key-1"


# --------------------------------------------------------------------------- #
# Key / token helpers
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def keypair():
    """An EC P-256 private PEM + matching public JWK (with kid/alg)."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    public_jwk = jwk.construct(public_pem, ALGORITHMS.ES256).to_dict()
    public_jwk["kid"] = TEST_KID
    public_jwk["alg"] = "ES256"
    public_jwk["use"] = "sig"
    return private_pem, public_jwk


@pytest.fixture(autouse=True)
def supabase_config(monkeypatch, keypair):
    """Enable Supabase auth pointing at the test issuer, with a stubbed JWKS."""
    _private_pem, public_jwk = keypair
    monkeypatch.setattr(settings, "SUPABASE_URL", TEST_ISSUER_BASE)
    monkeypatch.setattr(settings, "SUPABASE_PROJECT_REF", None)
    monkeypatch.setattr(settings, "SUPABASE_JWKS_URL", None)
    monkeypatch.setattr(settings, "SUPABASE_JWT_ISSUER", None)
    # Stub the network fetch and clear any cached keys.
    monkeypatch.setattr(sa, "_fetch_jwks", lambda: [public_jwk])
    sa._reset_cache_for_tests()
    yield
    sa._reset_cache_for_tests()


def make_token(private_pem, *, sub=None, email="user@example.com",
               aud="authenticated", iss=TEST_ISSUER, exp_delta=3600,
               kid=TEST_KID, metadata=None):
    now = int(time.time())
    claims = {
        "sub": sub or str(uuid.uuid4()),
        "aud": aud,
        "iss": iss,
        "role": "authenticated",
        "email": email,
        "iat": now,
        "exp": now + exp_delta,
    }
    if metadata is not None:
        claims["user_metadata"] = metadata
    return jwt.encode(claims, private_pem, algorithm="ES256", headers={"kid": kid})


# --------------------------------------------------------------------------- #
# Pure verification
# --------------------------------------------------------------------------- #
def test_verify_valid_token_returns_claims(keypair):
    private_pem, _ = keypair
    sub = str(uuid.uuid4())
    token = make_token(private_pem, sub=sub, email="a@b.com")
    claims = sa.verify_supabase_token(token)
    assert claims["sub"] == sub
    assert claims["email"] == "a@b.com"


def test_verify_rejects_wrong_issuer(keypair):
    private_pem, _ = keypair
    token = make_token(private_pem, iss="https://evil.example.com/auth/v1")
    with pytest.raises(sa.SupabaseAuthError):
        sa.verify_supabase_token(token)


def test_verify_rejects_wrong_audience(keypair):
    private_pem, _ = keypair
    token = make_token(private_pem, aud="some-other-aud")
    with pytest.raises(sa.SupabaseAuthError):
        sa.verify_supabase_token(token)


def test_verify_rejects_expired(keypair):
    private_pem, _ = keypair
    token = make_token(private_pem, exp_delta=-10)
    with pytest.raises(sa.SupabaseAuthError):
        sa.verify_supabase_token(token)


def test_verify_rejects_bad_signature(keypair):
    private_pem, _ = keypair
    # Sign with a DIFFERENT key than the one published in the JWKS.
    other = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    token = make_token(other)
    with pytest.raises(sa.SupabaseAuthError):
        sa.verify_supabase_token(token)


def test_verify_rejects_unknown_kid(keypair):
    private_pem, _ = keypair
    token = make_token(private_pem, kid="nonexistent-kid")
    with pytest.raises(sa.SupabaseAuthError):
        sa.verify_supabase_token(token)


def test_looks_like_supabase_token_routing(keypair):
    private_pem, _ = keypair
    supa = make_token(private_pem)
    legacy = create_access_token(data={"sub": str(uuid.uuid4())})
    assert sa.looks_like_supabase_token(supa) is True
    assert sa.looks_like_supabase_token(legacy) is False
    assert sa.looks_like_supabase_token("not-a-jwt") is False


# --------------------------------------------------------------------------- #
# Dual-accept dependency via the live /auth/me endpoint
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


def test_supabase_token_auto_provisions_profile(keypair, db, client):
    private_pem, _ = keypair
    sub = str(uuid.uuid4())
    token = make_token(
        private_pem, sub=sub, email="new@example.com",
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


def test_supabase_token_resolves_existing_profile(keypair, db, client):
    private_pem, _ = keypair
    sub = uuid.uuid4()
    db.add(User(id=sub, email="existing@example.com", hashed_password="",
                full_name="Existing"))
    db.commit()

    token = make_token(private_pem, sub=str(sub), email="existing@example.com")
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == str(sub)
    db.expire_all()
    assert db.query(User).filter(User.email == "existing@example.com").count() == 1


def test_legacy_jwt_still_authenticates(keypair, db, client):
    user = User(email="legacy@example.com", hashed_password="x", full_name="Legacy")
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(data={"sub": str(user.id)})
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] == "legacy@example.com"


def test_garbage_token_is_rejected(db, client):
    resp = client.get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert resp.status_code == 401
