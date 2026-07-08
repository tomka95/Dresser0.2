"""Signed, short-lived OAuth `state` for the Calendar-connect flow (CSRF defense).

A verbatim mirror of app/core/gmail_oauth_state.py with ONE deliberate
difference: the `purpose` claim is ``calendar_oauth_connect``. That difference is
the security point of this module — a state token minted for the Gmail flow
(purpose ``gmail_oauth_connect``) is REJECTED here on the purpose check, so a
Gmail consent round-trip can never be replayed into the calendar callback to
attach a calendar grant the user never consented to. Even if both flows were
configured with the same signing secret (so the signature validated), the
purpose binding still blocks the cross-flow replay.

    { "sub": <user_id>, "purpose": "calendar_oauth_connect", "jti": <random>,
      "iat": ..., "exp": ... }

Signed with a dedicated secret (CALENDAR_OAUTH_STATE_SECRET), independent of both
the login JWT secret and the Gmail state secret.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.core.config import settings

_ALG = "HS256"
_PURPOSE = "calendar_oauth_connect"


class OAuthStateError(RuntimeError):
    """Raised when the OAuth state secret is missing or a state is invalid."""


def _secret() -> str:
    secret = settings.CALENDAR_OAUTH_STATE_SECRET
    if not secret:
        raise OAuthStateError(
            "CALENDAR_OAUTH_STATE_SECRET is not set; cannot sign/verify the "
            "calendar OAuth state parameter."
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
        "exp": now + timedelta(seconds=settings.CALENDAR_OAUTH_STATE_TTL_SECONDS),
    }
    return jwt.encode(claims, _secret(), algorithm=_ALG)


def verify_state(state: str, *, expected_user_id: str) -> None:
    """Validate signature, expiry, purpose, and user binding. Raises on failure."""
    try:
        claims = jwt.decode(state, _secret(), algorithms=[_ALG])
    except JWTError as exc:
        raise OAuthStateError("Invalid or expired OAuth state.") from exc

    if claims.get("purpose") != _PURPOSE:
        # A state minted for a DIFFERENT OAuth flow (e.g. Gmail) — reject rather
        # than let it attach a calendar grant.
        raise OAuthStateError("OAuth state has the wrong purpose.")
    if claims.get("sub") != str(expected_user_id):
        raise OAuthStateError("OAuth state does not match the authenticated user.")
