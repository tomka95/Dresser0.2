"""Supabase Auth JWT verification.

Supabase Auth (auth.users) is the identity source we are migrating to. Access
tokens it issues are JWTs signed with the project's **asymmetric** signing keys.
We verify them against the project's public keys, published as a JWKS document at:

    {SUPABASE_URL}/auth/v1/.well-known/jwks.json

This module only ever handles PUBLIC key material — it never needs, and never
uses, the legacy shared HS256 JWT secret. Verification checks the signature plus
the `iss`, `aud`, and `exp` claims.

Design notes
------------
* The JWKS is fetched lazily and cached in-process with a TTL. On a `kid` we have
  not seen (e.g. after a key rotation) we force a single refresh before failing,
  so rotations heal automatically without a restart.
* A `threading.Lock` guards the cache because FastAPI runs sync dependencies in a
  threadpool, so `get_current_user` can call in here from multiple threads.
* If asymmetric signing keys are not yet enabled on the project, the JWKS is empty
  (`{"keys": []}`) and verification of any Supabase token fails loudly with
  `SupabaseAuthError`. Enabling asymmetric ("JWT signing keys") in the Supabase
  dashboard is the operator prerequisite for the Supabase path to accept tokens.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

import httpx
from jose import jwt
from jose.exceptions import JWTError

from app.core.config import settings

logger = logging.getLogger(__name__)


class SupabaseAuthError(Exception):
    """Raised when a token cannot be verified as a valid Supabase access token."""


# Asymmetric algorithms Supabase uses for signing keys. HS* is intentionally
# excluded: this module verifies with public keys only.
_ALLOWED_ALGORITHMS = ("ES256", "RS256", "EdDSA")

# In-process JWKS cache.
_jwks_lock = threading.Lock()
_jwks_keys: Optional[List[Dict[str, Any]]] = None
_jwks_fetched_at: float = 0.0


def _cache_is_fresh(now: float) -> bool:
    return (
        _jwks_keys is not None
        and (now - _jwks_fetched_at) < settings.SUPABASE_JWKS_CACHE_TTL_SECONDS
    )


def _fetch_jwks() -> List[Dict[str, Any]]:
    """Fetch the JWKS document from the project's well-known endpoint."""
    url = settings.supabase_jwks_url
    if not url:
        raise SupabaseAuthError("Supabase JWKS URL is not configured.")
    try:
        resp = httpx.get(url, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # network error, non-2xx, bad JSON
        raise SupabaseAuthError(f"Failed to fetch Supabase JWKS: {exc}") from exc
    keys = data.get("keys")
    if not isinstance(keys, list):
        raise SupabaseAuthError("Supabase JWKS response did not contain a 'keys' list.")
    return keys


def _get_jwks(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """Return cached JWKS keys, refreshing when stale or when forced."""
    global _jwks_keys, _jwks_fetched_at
    now = time.monotonic()
    if not force_refresh and _cache_is_fresh(now):
        return _jwks_keys  # type: ignore[return-value]
    with _jwks_lock:
        # Re-check under the lock so we don't stampede concurrent refreshes.
        now = time.monotonic()
        if not force_refresh and _cache_is_fresh(now):
            return _jwks_keys  # type: ignore[return-value]
        _jwks_keys = _fetch_jwks()
        _jwks_fetched_at = now
        return _jwks_keys


def _find_key(kid: Optional[str], keys: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Select a signing key by `kid` (or the sole key when no kid is present)."""
    if kid is None:
        return keys[0] if len(keys) == 1 else None
    for key in keys:
        if key.get("kid") == kid:
            return key
    return None


def _signing_key_for(token: str) -> Dict[str, Any]:
    """Resolve the JWK that signed `token`, refreshing once on a kid miss."""
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise SupabaseAuthError(f"Malformed token header: {exc}") from exc

    kid = header.get("kid")
    key = _find_key(kid, _get_jwks())
    if key is None:
        # Unknown kid: keys may have rotated. Force one refresh before giving up.
        key = _find_key(kid, _get_jwks(force_refresh=True))
    if key is None:
        raise SupabaseAuthError(
            "No matching Supabase signing key found for token "
            f"(kid={kid!r}). The project may not have asymmetric JWT signing "
            "keys enabled yet."
        )
    return key


def verify_supabase_token(token: str) -> Dict[str, Any]:
    """Verify a Supabase access token and return its validated claims.

    Validates the asymmetric signature against the project's JWKS and enforces the
    expected issuer, audience, and expiry. Raises SupabaseAuthError on any failure.
    """
    if not settings.supabase_auth_enabled:
        raise SupabaseAuthError("Supabase Auth is not configured.")

    key = _signing_key_for(token)
    alg = key.get("alg")
    algorithms = [alg] if alg in _ALLOWED_ALGORITHMS else list(_ALLOWED_ALGORITHMS)

    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=algorithms,
            audience=settings.SUPABASE_JWT_AUDIENCE,
            issuer=settings.supabase_jwt_issuer,
            options={
                "verify_signature": True,
                "verify_aud": True,
                "verify_iss": True,
                "verify_exp": True,
                "require_exp": True,
            },
        )
    except JWTError as exc:
        raise SupabaseAuthError(f"Supabase token verification failed: {exc}") from exc

    if not claims.get("sub"):
        raise SupabaseAuthError("Supabase token is missing the 'sub' claim.")
    return claims


def _reset_cache_for_tests() -> None:
    """Clear the in-process JWKS cache (test hook only)."""
    global _jwks_keys, _jwks_fetched_at
    with _jwks_lock:
        _jwks_keys = None
        _jwks_fetched_at = 0.0
