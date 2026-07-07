"""Auth-hardening regression tests (fix/auth-hardening — closes ARCHITECTURE_AUDIT S1/S2).

Proves the account-takeover + IDOR surfaces are closed:
  * legacy HS256 / custom / 'none'-alg tokens are rejected (only asymmetric
    Supabase tokens are accepted),
  * forged (foreign-key) signatures are rejected,
  * an UNCONFIGURED Supabase verifier fails CLOSED — no forgeable fallback key,
  * the removed unauthenticated/legacy endpoints are gone,
  * the forgeable JWT_SECRET_KEY setting no longer exists.
"""

import time
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from jose import jwt

import app.supabase_auth as sa
from app.core.config import settings
from app.db import Base, SessionLocal, engine
from main import app
from tests._authutil import TEST_ISSUER, mint_supabase_token


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


def _hs256_token(sub=None, secret="any-shared-secret", iss=TEST_ISSUER) -> str:
    """A legacy-style SYMMETRIC HS256 token (the retired custom-JWT shape)."""
    now = int(time.time())
    claims = {
        "sub": sub or str(uuid.uuid4()),
        "iss": iss,
        "aud": "authenticated",
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(claims, secret, algorithm="HS256")


def _none_alg_token(sub=None) -> str:
    """An UNSIGNED ('alg: none') token, hand-assembled."""
    import base64
    import json

    def b64(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    header = b64({"alg": "none", "typ": "JWT"})
    payload = b64({
        "sub": sub or str(uuid.uuid4()),
        "iss": TEST_ISSUER,
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
    })
    return f"{header}.{payload}."


# --------------------------------------------------------------------------- #
# S1 — only asymmetric Supabase tokens are accepted
# --------------------------------------------------------------------------- #
def test_hs256_custom_token_rejected_at_verify():
    with pytest.raises(sa.SupabaseAuthError):
        sa.verify_supabase_token(_hs256_token())


def test_hs256_custom_token_rejected_at_endpoint(db, client):
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {_hs256_token()}"})
    assert resp.status_code == 401


def test_none_alg_token_rejected_at_endpoint(db, client):
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {_none_alg_token()}"})
    assert resp.status_code == 401


def test_forged_signature_rejected_at_endpoint(db, client):
    foreign_pem = (
        ec.generate_private_key(ec.SECP256R1())
        .private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        .decode()
    )
    token = mint_supabase_token(key=foreign_pem)  # right shape, wrong key
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_unconfigured_supabase_fails_closed(db, client, monkeypatch):
    """With Supabase unconfigured, EVERY token is rejected — no forgeable fallback."""
    monkeypatch.setattr(settings, "SUPABASE_URL", None)
    monkeypatch.setattr(settings, "SUPABASE_PROJECT_REF", None)
    monkeypatch.setattr(settings, "SUPABASE_JWKS_URL", None)
    monkeypatch.setattr(settings, "SUPABASE_JWT_ISSUER", None)
    assert settings.supabase_auth_enabled is False

    # A token that WOULD be valid if Supabase were configured.
    token = mint_supabase_token()
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# S2 — the unauthenticated / legacy endpoints are gone
# --------------------------------------------------------------------------- #
def test_removed_legacy_endpoints_are_gone(client):
    assert client.post("/signup", data={"email": "a@b.com", "password": "x"}).status_code == 404
    assert client.post("/login", data={"email": "a@b.com", "password": "x"}).status_code == 404
    assert client.post("/users", params={"email": "a@b.com"}).status_code == 404
    assert client.post(
        f"/users/{uuid.uuid4()}/clothing", params={"name": "x"}
    ).status_code == 404


# --------------------------------------------------------------------------- #
# S1 — the forgeable shared-secret setting no longer exists
# --------------------------------------------------------------------------- #
def test_no_forgeable_jwt_secret_setting():
    assert not hasattr(settings, "JWT_SECRET_KEY")
    assert not hasattr(settings, "JWT_ALGORITHM")
    assert not hasattr(settings, "JWT_ACCESS_TOKEN_EXPIRE_MINUTES")
