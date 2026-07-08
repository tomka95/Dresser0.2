"""Calendar-connect OAuth: obtain + securely store a calendar.events.readonly
refresh token. Auth/token PLUMBING ONLY — it reads no events (those are fetched
live elsewhere).

A verbatim mirror of app/api/routes/gmail_oauth.py, on a SEPARATE dedicated
Google client (CALENDAR_OAUTH_*) with the calendar.events.readonly scope. The
Next.js Route Handler relays; this backend does the secret-bearing work.

  1. GET  /calendar/oauth/start      -> Google consent URL + signed `state`
                                        (purpose=calendar_oauth_connect, user-bound).
  2. (browser consents; Google redirects to the Next.js /calendar/oauth/callback
     handler, which POSTs code+state here)
  3. POST /calendar/oauth/exchange   -> validate state, exchange code (redirect_uri
                                        from ENV only), write ENCRYPTED tokens.
  4. GET  /calendar/oauth/status     -> {connected, scope, connected_at}.
  5. POST /calendar/oauth/disconnect -> REVOKE the grant at Google AND wipe tokens.

Security notes:
  * No authorization code, token, or state is ever logged or returned in a URL.
  * redirect_uri is server-fixed (env only) — no caller-supplied redirect.
  * A Gmail-issued state CANNOT be replayed here: verify_state requires
    purpose == calendar_oauth_connect.
  * Tokens are encrypted at rest (app/core/token_crypto); plaintext exists only
    transiently in memory during exchange/refresh/revoke.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.calendar_oauth_state import OAuthStateError, issue_state, verify_state
from app.core.config import settings
from app.core.token_crypto import TokenCryptoError, decrypt_token, encrypt_token
from app.dependencies import get_current_user, get_db
from app.models import CalendarAccount, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendar/oauth", tags=["calendar-oauth"])

_GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_GOOGLE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"


def _require_client_config() -> None:
    if not settings.CALENDAR_OAUTH_CLIENT_ID or not settings.CALENDAR_OAUTH_CLIENT_SECRET:
        logger.error("Calendar OAuth client not configured (CALENDAR_OAUTH_CLIENT_ID/SECRET).")
        raise HTTPException(
            status_code=500,
            detail="Calendar connection is not configured on the server.",
        )


class StartResponse(BaseModel):
    url: str


@router.get("/start", response_model=StartResponse)
def start_calendar_oauth(current_user: User = Depends(get_current_user)) -> StartResponse:
    """Build the Google consent URL for calendar.events.readonly, bound to this user."""
    _require_client_config()
    try:
        state = issue_state(str(current_user.id))
    except OAuthStateError as exc:
        logger.error("Cannot issue calendar OAuth state: %s", exc)
        raise HTTPException(status_code=500, detail="Calendar connection is not configured.")

    params = {
        "client_id": settings.CALENDAR_OAUTH_CLIENT_ID,
        "redirect_uri": settings.CALENDAR_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": settings.CALENDAR_OAUTH_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "false",
        "state": state,
    }
    url = f"{_GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"
    logger.info("Issued calendar consent URL for user %s", current_user.id)
    return StartResponse(url=url)


class ExchangeRequest(BaseModel):
    code: str
    state: str
    # NOTE: deliberately NO redirect_uri — the backend uses env only.


class ConnectionStatus(BaseModel):
    connected: bool
    scope: Optional[str] = None
    connected_at: Optional[str] = None


@router.post("/exchange", response_model=ConnectionStatus)
def exchange_calendar_code(
    body: ExchangeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConnectionStatus:
    """Validate state, exchange the auth code, and store ENCRYPTED tokens."""
    _require_client_config()

    # 1) CSRF + cross-flow-replay defense: ours, fresh, THIS user, calendar purpose.
    try:
        verify_state(body.state, expected_user_id=str(current_user.id))
    except OAuthStateError as exc:
        logger.warning("Rejected calendar OAuth state for user %s: %s", current_user.id, exc)
        raise HTTPException(status_code=400, detail="Invalid or expired authorization state.")

    # 2) Exchange code -> tokens. redirect_uri is server-fixed (env only).
    token_data = {
        "code": body.code,
        "client_id": settings.CALENDAR_OAUTH_CLIENT_ID,
        "client_secret": settings.CALENDAR_OAUTH_CLIENT_SECRET,
        "redirect_uri": settings.CALENDAR_OAUTH_REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    try:
        resp = httpx.post(
            _GOOGLE_TOKEN_ENDPOINT,
            data=token_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10.0,
        )
        resp.raise_for_status()
        tokens = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.error("Calendar code exchange failed: HTTP %s", exc.response.status_code)
        raise HTTPException(status_code=400, detail="Failed to exchange authorization code.")
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected error during calendar code exchange")
        raise HTTPException(status_code=502, detail="Failed to reach Google token endpoint.")

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    expires_in = int(tokens.get("expires_in", 3600))
    granted_scope = tokens.get("scope", settings.CALENDAR_OAUTH_SCOPE)

    if not access_token:
        raise HTTPException(status_code=400, detail="Google did not return an access token.")
    if not refresh_token:
        logger.warning("Calendar exchange returned no refresh_token for user %s", current_user.id)
        raise HTTPException(
            status_code=400,
            detail="Google did not return a refresh token. Please try connecting again.",
        )

    # 3) Encrypt before tokens touch the DB / ORM.
    try:
        enc_access = encrypt_token(access_token, field="access_token")
        enc_refresh = encrypt_token(refresh_token, field="refresh_token")
    except TokenCryptoError as exc:
        logger.error("Token encryption unavailable: %s", exc)
        raise HTTPException(status_code=500, detail="Server cannot securely store the connection.")

    token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    # 4) Upsert the per-user calendar_accounts row (UNIQUE(user_id)).
    account = db.query(CalendarAccount).filter(CalendarAccount.user_id == current_user.id).first()
    if account is None:
        account = CalendarAccount(user_id=current_user.id)
        db.add(account)
    account.access_token = enc_access
    account.refresh_token = enc_refresh
    account.scope = granted_scope
    account.token_expiry = token_expiry

    db.commit()
    db.refresh(account)

    logger.info("Stored encrypted calendar tokens for user %s", current_user.id)
    return ConnectionStatus(
        connected=True, scope=account.scope, connected_at=_iso(account.created_at)
    )


@router.get("/status", response_model=ConnectionStatus)
def calendar_connection_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConnectionStatus:
    """Report whether the user has a usable (refresh-token-bearing) connection.
    Never returns any token material."""
    account = db.query(CalendarAccount).filter(CalendarAccount.user_id == current_user.id).first()
    connected = bool(account and account.refresh_token)
    return ConnectionStatus(
        connected=connected,
        scope=account.scope if connected else None,
        connected_at=_iso(account.created_at) if connected else None,
    )


class DisconnectResponse(BaseModel):
    connected: bool = False


@router.post("/disconnect", response_model=DisconnectResponse)
def disconnect_calendar(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DisconnectResponse:
    """Revoke the grant at Google AND wipe the stored tokens.

    Best-effort revoke (a Google-side failure must not strand the user with an
    un-deletable row); the local token wipe is unconditional.
    """
    account = db.query(CalendarAccount).filter(CalendarAccount.user_id == current_user.id).first()
    if account is None:
        return DisconnectResponse(connected=False)

    # Revoke at Google so the refresh token is dead even outside our DB.
    if account.refresh_token:
        try:
            refresh_plain = decrypt_token(account.refresh_token, field="refresh_token")
            httpx.post(
                _GOOGLE_REVOKE_ENDPOINT,
                data={"token": refresh_plain},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10.0,
            )
        except Exception:  # noqa: BLE001 — never log token material; wipe regardless
            logger.warning("Calendar token revoke call failed for user %s (wiping anyway)", current_user.id)

    db.delete(account)
    db.commit()
    logger.info("Disconnected calendar for user %s", current_user.id)
    return DisconnectResponse(connected=False)


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if isinstance(value, datetime) else None
