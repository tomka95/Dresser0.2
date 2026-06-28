"""At-rest encryption for OAuth tokens stored in google_accounts.

Mechanism: app-level envelope encryption with AES-256-GCM.

Why app-level AES-GCM (over Supabase Vault):
  * The encryption key lives ONLY in the application environment
    (GMAIL_TOKEN_ENC_KEY), never in the database. A compromise of the database
    alone -- the primary "at rest" threat -- therefore yields only ciphertext.
    With Supabase Vault the decryption keypath lives next to the data inside the
    same Postgres instance, so a DB/role compromise can reach plaintext.
  * No new dependency: `cryptography` is already present (pulled in by
    python-jose[cryptography]).
  * Decryption is centralized: only the token-refresh service ever calls
    decrypt_token(), so plaintext exposure is a single, auditable code path.

Ciphertext format (stored as text in the existing token columns):

    v1:<base64url( nonce[12] || ciphertext || gcm_tag[16] )>

  * `v1:` is a key/format version prefix so the key can be rotated later by
    introducing `v2:` and trying keys in order.
  * AES-GCM is authenticated: tampering or using the wrong key fails the tag
    check and raises, rather than returning garbage.
  * Associated data (AAD) binds each ciphertext to its logical field name
    (e.g. "refresh_token"), so a stored refresh-token blob cannot be swapped
    into the access-token column (or vice versa) and still decrypt.
"""

from __future__ import annotations

import base64
import os
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

_VERSION_PREFIX = "v1:"
_NONCE_BYTES = 12  # 96-bit nonce, the AES-GCM standard/recommended size


class TokenCryptoError(RuntimeError):
    """Raised when token encryption/decryption is misconfigured or fails."""


@lru_cache(maxsize=1)
def _key() -> bytes:
    """Return the 32-byte AES key, decoded from the base64 env value.

    Cached so we validate the key once. Raises a clear error if the key is
    missing or not a valid 32-byte (AES-256) key, rather than failing obscurely
    deep inside a token write.
    """
    raw = settings.GMAIL_TOKEN_ENC_KEY
    if not raw:
        raise TokenCryptoError(
            "GMAIL_TOKEN_ENC_KEY is not set. Generate one with "
            "`python -c \"import os,base64;print(base64.b64encode(os.urandom(32)).decode())\"` "
            "and set it in the backend environment. It must NOT be committed or "
            "stored in the database."
        )
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception as exc:  # noqa: BLE001 - normalize to one clear error
        raise TokenCryptoError("GMAIL_TOKEN_ENC_KEY must be valid base64.") from exc
    if len(key) != 32:
        raise TokenCryptoError(
            f"GMAIL_TOKEN_ENC_KEY must decode to 32 bytes (AES-256); got {len(key)}."
        )
    return key


def encrypt_token(plaintext: str, *, field: str) -> str:
    """Encrypt a token string for storage. `field` is bound as AES-GCM AAD.

    `field` should be the logical column name ("access_token"/"refresh_token")
    so ciphertext is non-transferable between fields.
    """
    if plaintext is None:
        raise TokenCryptoError("Refusing to encrypt None.")
    aesgcm = AESGCM(_key())
    nonce = os.urandom(_NONCE_BYTES)
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), field.encode("utf-8"))
    blob = base64.urlsafe_b64encode(nonce + ct).decode("ascii")
    return f"{_VERSION_PREFIX}{blob}"


def decrypt_token(stored: str, *, field: str) -> str:
    """Decrypt a value produced by encrypt_token(). Raises on tamper/wrong key."""
    if not stored or not stored.startswith(_VERSION_PREFIX):
        raise TokenCryptoError(
            "Stored token is not in the expected encrypted format "
            f"({_VERSION_PREFIX}...). Refusing to use it."
        )
    blob = stored[len(_VERSION_PREFIX):]
    try:
        raw = base64.urlsafe_b64decode(blob.encode("ascii"))
    except Exception as exc:  # noqa: BLE001
        raise TokenCryptoError("Stored token is not valid base64.") from exc
    if len(raw) <= _NONCE_BYTES:
        raise TokenCryptoError("Stored token is too short to be valid ciphertext.")
    nonce, ct = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:]
    try:
        pt = AESGCM(_key()).decrypt(nonce, ct, field.encode("utf-8"))
    except InvalidTag as exc:
        raise TokenCryptoError(
            "Token authentication failed (wrong key, wrong field, or tampered "
            "ciphertext)."
        ) from exc
    return pt.decode("utf-8")
