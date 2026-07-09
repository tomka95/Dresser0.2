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
# Two DISTINCT purposes on the SAME gmail.readonly client. Both are valid Gmail-connect
# states, but ONLY the onboarding purpose auto-starts the background receipt scan on
# exchange. verify_state pins the expected purpose, so an onboarding state can NEVER be
# replayed as a plain connect (or vice versa) — the exact cross-flow replay guard the
# calendar flow uses against a Gmail state (Wave C / Fix 1).
_PURPOSE = "gmail_oauth_connect"                 # plain connect (default; unchanged)
_PURPOSE_ONBOARDING = "gmail_oauth_onboarding"   # onboarding connect -> auto-scan
_VALID_PURPOSES = frozenset({_PURPOSE, _PURPOSE_ONBOARDING})


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


def issue_state(user_id: str, *, purpose: str = _PURPOSE) -> str:
    """Mint a signed state token bound to user_id + purpose, valid for the configured TTL."""
    if purpose not in _VALID_PURPOSES:
        raise OAuthStateError(f"Unknown OAuth state purpose: {purpose!r}")
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),
        "purpose": purpose,
        "jti": secrets.token_urlsafe(16),
        "iat": now,
        "exp": now + timedelta(seconds=settings.GMAIL_OAUTH_STATE_TTL_SECONDS),
    }
    return jwt.encode(claims, _secret(), algorithm=_ALG)


def verify_state(
    state: str, *, expected_user_id: str, expected_purpose: str = _PURPOSE
) -> None:
    """Validate signature, expiry, user binding, AND the EXACT expected purpose.

    Raises OAuthStateError on any mismatch. Pinning ``expected_purpose`` is the replay
    guard: a state minted for one purpose (plain connect vs onboarding) is rejected on the
    other path, so only a genuine onboarding-purpose state can trigger the auto-scan."""
    try:
        claims = jwt.decode(state, _secret(), algorithms=[_ALG])
    except JWTError as exc:
        raise OAuthStateError("Invalid or expired OAuth state.") from exc

    if claims.get("purpose") != expected_purpose:
        raise OAuthStateError("OAuth state has the wrong purpose.")
    if claims.get("sub") != str(expected_user_id):
        # State was issued for a different user than the one now authenticated.
        raise OAuthStateError("OAuth state does not match the authenticated user.")


def read_state_purpose(state: str, *, expected_user_id: str) -> str:
    """Verify signature + expiry + user binding, and RETURN the state's validated purpose.

    The single gmail exchange endpoint branches plain-connect vs onboarding on the result.
    Because the purpose is inside the SIGNED state, a plain-connect state can never yield
    the onboarding purpose (so it can never trigger the auto-scan), and a forged/foreign
    state is rejected here exactly as verify_state would. Returns one of _VALID_PURPOSES."""
    try:
        claims = jwt.decode(state, _secret(), algorithms=[_ALG])
    except JWTError as exc:
        raise OAuthStateError("Invalid or expired OAuth state.") from exc

    purpose = claims.get("purpose")
    if purpose not in _VALID_PURPOSES:
        raise OAuthStateError("OAuth state has an unknown purpose.")
    if claims.get("sub") != str(expected_user_id):
        raise OAuthStateError("OAuth state does not match the authenticated user.")
    return purpose
