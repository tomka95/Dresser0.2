"""Signed, short-lived OAuth `state` for the Gmail-connect flow (CSRF defense).

The `state` parameter is round-tripped through Google's consent screen and must
prove, on return, that *this* authorization was initiated by *this* user and is
still fresh. We encode it as a short-lived HS256 JWT:

    { "sub": <user_id>, "purpose": "gmail_oauth_connect", "jti": <random>,
      "iat": ..., "exp": ... }

On callback the backend independently authenticates the Supabase user, then
requires state.sub == that user's id. An attacker cannot forge state (no secret)
nor replay another user's state (sub binding + short TTL). Signed with a
dedicated secret, separate from the login JWT secret.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.core.config import settings

_ALG = "HS256"
_PURPOSE = "gmail_oauth_connect"


class OAuthStateError(RuntimeError):
    """Raised when the OAuth state secret is missing or a state is invalid."""


def _secret() -> str:
    secret = settings.GMAIL_OAUTH_STATE_SECRET
    if not secret:
        raise OAuthStateError(
            "GMAIL_OAUTH_STATE_SECRET is not set; cannot sign/verify the OAuth "
            "state parameter."
        )
    return secret


def issue_state(user_id: str) -> str:
    """Mint a signed state token bound to user_id, valid for the configured TTL."""
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),
        "purpose": _PURPOSE,
        "jti": secrets.token_urlsafe(16),
        "iat": now,
        "exp": now + timedelta(seconds=settings.GMAIL_OAUTH_STATE_TTL_SECONDS),
    }
    return jwt.encode(claims, _secret(), algorithm=_ALG)


def verify_state(state: str, *, expected_user_id: str) -> None:
    """Validate signature, expiry, purpose, and user binding. Raises on failure."""
    try:
        claims = jwt.decode(state, _secret(), algorithms=[_ALG])
    except JWTError as exc:
        raise OAuthStateError("Invalid or expired OAuth state.") from exc

    if claims.get("purpose") != _PURPOSE:
        raise OAuthStateError("OAuth state has the wrong purpose.")
    if claims.get("sub") != str(expected_user_id):
        # State was issued for a different user than the one now authenticated.
        raise OAuthStateError("OAuth state does not match the authenticated user.")
