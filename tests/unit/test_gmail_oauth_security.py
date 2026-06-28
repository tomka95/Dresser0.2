"""Unit tests for the Gmail-connect security primitives:

  * app/core/token_crypto.py  — AES-256-GCM at-rest token encryption
  * app/core/gmail_oauth_state.py — signed, user-bound OAuth state (CSRF)

These are pure crypto/JWT helpers with no DB or network dependency.
"""

import base64

import pytest

from app.core import token_crypto
from app.core.config import settings
from app.core.gmail_oauth_state import (
    OAuthStateError,
    issue_state,
    verify_state,
)
from app.core.token_crypto import (
    TokenCryptoError,
    decrypt_token,
    encrypt_token,
)

_TEST_KEY = base64.b64encode(b"0" * 32).decode()


@pytest.fixture(autouse=True)
def _crypto_env(monkeypatch):
    """Provide deterministic secrets and reset the cached key per test."""
    monkeypatch.setattr(settings, "GMAIL_TOKEN_ENC_KEY", _TEST_KEY, raising=False)
    monkeypatch.setattr(settings, "GMAIL_OAUTH_STATE_SECRET", "test-state-secret", raising=False)
    token_crypto._key.cache_clear()
    yield
    token_crypto._key.cache_clear()


# --- token_crypto -----------------------------------------------------------

def test_encrypt_decrypt_round_trips():
    secret = "1//0g-super-secret-refresh-token"
    blob = encrypt_token(secret, field="refresh_token")
    assert blob.startswith("v1:")
    assert secret not in blob  # ciphertext, not plaintext
    assert decrypt_token(blob, field="refresh_token") == secret


def test_ciphertext_is_nondeterministic():
    a = encrypt_token("same", field="access_token")
    b = encrypt_token("same", field="access_token")
    assert a != b  # random nonce per encryption


def test_field_binding_prevents_cross_field_reuse():
    blob = encrypt_token("token", field="refresh_token")
    # Decrypting with a different field (AAD) must fail the GCM tag check.
    with pytest.raises(TokenCryptoError):
        decrypt_token(blob, field="access_token")


def test_tampered_ciphertext_is_rejected():
    blob = encrypt_token("token", field="access_token")
    tampered = blob[:-2] + ("AA" if not blob.endswith("AA") else "BB")
    with pytest.raises(TokenCryptoError):
        decrypt_token(tampered, field="access_token")


def test_rejects_unencrypted_value():
    with pytest.raises(TokenCryptoError):
        decrypt_token("plaintext-not-encrypted", field="access_token")


def test_missing_key_raises(monkeypatch):
    monkeypatch.setattr(settings, "GMAIL_TOKEN_ENC_KEY", None, raising=False)
    token_crypto._key.cache_clear()
    with pytest.raises(TokenCryptoError):
        encrypt_token("x", field="access_token")


# --- oauth state ------------------------------------------------------------

def test_state_round_trips_for_same_user():
    state = issue_state("user-123")
    verify_state(state, expected_user_id="user-123")  # no raise


def test_state_rejected_for_different_user():
    state = issue_state("user-123")
    with pytest.raises(OAuthStateError):
        verify_state(state, expected_user_id="user-999")


def test_tampered_state_rejected():
    state = issue_state("user-123")
    with pytest.raises(OAuthStateError):
        verify_state(state + "x", expected_user_id="user-123")


def test_state_signed_with_other_secret_rejected(monkeypatch):
    state = issue_state("user-123")
    monkeypatch.setattr(settings, "GMAIL_OAUTH_STATE_SECRET", "different-secret", raising=False)
    with pytest.raises(OAuthStateError):
        verify_state(state, expected_user_id="user-123")
