"""Gmail-connect OAuth: obtain and securely store a gmail.readonly refresh token.

This is auth/token PLUMBING ONLY. It does not fetch, parse, or ingest any email
-- it just lets an authenticated user connect their Gmail and leaves a usable,
encrypted refresh token in google_accounts.

Flow (mirrors the Supabase login callback split: Next.js Route Handler relays,
backend does the secret-bearing work):

  1. GET  /gmail/oauth/start     -> builds the Google consent URL (GMAIL_OAUTH_*
                                    client only) with a signed `state` bound to
                                    the authenticated user. Returns {url}.
  2. (browser visits Google, consents, Google redirects to the Next.js handler
     /gmail/oauth/callback, which POSTs the code+state here)
  3. POST /gmail/oauth/exchange  -> validates state, exchanges the code for tokens
                                    using GMAIL_OAUTH_REDIRECT_URI from ENV ONLY
                                    (never a caller-supplied redirect_uri), and
                                    writes ENCRYPTED tokens to google_accounts.
  4. GET  /gmail/oauth/status    -> {connected, scope, connected_at} for the UI.

Security notes:
  * No authorization code, token, or state is ever logged or returned in a URL.
  * redirect_uri is server-fixed; the open-redirect foot-gun of the retired
    /auth/google endpoint is structurally impossible here.
  * Tokens are encrypted at rest (app/core/token_crypto); plaintext exists only
    transiently in memory during exchange/refresh.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.gmail_oauth_state import OAuthStateError, issue_state, verify_state
from app.core.token_crypto import TokenCryptoError, encrypt_token
from app.dependencies import get_current_user, get_db
from app.models import GoogleAccount, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gmail/oauth", tags=["gmail-oauth"])

_GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


def _require_client_config() -> None:
    """Fail loudly (500) if the dedicated Gmail client isn't configured."""
    if not settings.GMAIL_OAUTH_CLIENT_ID or not settings.GMAIL_OAUTH_CLIENT_SECRET:
        logger.error("Gmail OAuth client is not configured (GMAIL_OAUTH_CLIENT_ID/SECRET).")
        raise HTTPException(
            status_code=500,
            detail="Gmail connection is not configured on the server.",
        )


class StartResponse(BaseModel):
    url: str


@router.get("/start", response_model=StartResponse)
def start_gmail_oauth(
    current_user: User = Depends(get_current_user),
) -> StartResponse:
    """Build the Google consent URL for gmail.readonly, bound to this user.

    Uses the GMAIL_OAUTH_* client only, with access_type=offline + prompt=consent
    so Google returns a refresh token even on re-consent.
    """
    _require_client_config()
    try:
        state = issue_state(str(current_user.id))
    except OAuthStateError as exc:
        logger.error("Cannot issue OAuth state: %s", exc)
        raise HTTPException(status_code=500, detail="Gmail connection is not configured.")

    params = {
        "client_id": settings.GMAIL_OAUTH_CLIENT_ID,
        "redirect_uri": settings.GMAIL_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": settings.GMAIL_OAUTH_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "false",
        "state": state,
    }
    url = f"{_GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"
    logger.info("Issued Gmail consent URL for user %s", current_user.id)
    return StartResponse(url=url)


class ExchangeRequest(BaseModel):
    code: str
    state: str
    # NOTE: deliberately NO redirect_uri field. The backend uses
    # GMAIL_OAUTH_REDIRECT_URI from env exclusively.


class ConnectionStatus(BaseModel):
    connected: bool
    scope: Optional[str] = None
    connected_at: Optional[str] = None


@router.post("/exchange", response_model=ConnectionStatus)
def exchange_gmail_code(
    body: ExchangeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConnectionStatus:
    """Validate state, exchange the auth code, and store ENCRYPTED tokens."""
    _require_client_config()

    # 1) CSRF: the state must be ours, fresh, and minted for THIS user.
    try:
        verify_state(body.state, expected_user_id=str(current_user.id))
    except OAuthStateError as exc:
        logger.warning("Rejected Gmail OAuth state for user %s: %s", current_user.id, exc)
        raise HTTPException(status_code=400, detail="Invalid or expired authorization state.")

    # 2) Exchange code -> tokens. redirect_uri is server-fixed (env only).
    token_data = {
        "code": body.code,
        "client_id": settings.GMAIL_OAUTH_CLIENT_ID,
        "client_secret": settings.GMAIL_OAUTH_CLIENT_SECRET,
        "redirect_uri": settings.GMAIL_OAUTH_REDIRECT_URI,
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
        # Log status only -- never the response body (may echo the code/secret).
        logger.error("Gmail code exchange failed: HTTP %s", exc.response.status_code)
        raise HTTPException(status_code=400, detail="Failed to exchange authorization code.")
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected error during Gmail code exchange")
        raise HTTPException(status_code=502, detail="Failed to reach Google token endpoint.")

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    expires_in = int(tokens.get("expires_in", 3600))
    granted_scope = tokens.get("scope", settings.GMAIL_OAUTH_SCOPE)

    if not access_token:
        raise HTTPException(status_code=400, detail="Google did not return an access token.")
    if not refresh_token:
        # With prompt=consent + access_type=offline Google should always return a
        # refresh token. If it didn't, we can't do background ingestion -- surface
        # it rather than silently storing an access-token-only row.
        logger.warning("Gmail exchange returned no refresh_token for user %s", current_user.id)
        raise HTTPException(
            status_code=400,
            detail="Google did not return a refresh token. Please try connecting again.",
        )

    # 3) Encrypt before the tokens ever touch the DB / ORM.
    try:
        enc_access = encrypt_token(access_token, field="access_token")
        enc_refresh = encrypt_token(refresh_token, field="refresh_token")
    except TokenCryptoError as exc:
        logger.error("Token encryption unavailable: %s", exc)
        raise HTTPException(status_code=500, detail="Server cannot securely store the connection.")

    token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    # 4) Upsert the per-user google_accounts row (UNIQUE(user_id)).
    account = (
        db.query(GoogleAccount)
        .filter(GoogleAccount.user_id == current_user.id)
        .first()
    )
    if account is None:
        account = GoogleAccount(user_id=current_user.id)
        db.add(account)

    account.access_token = enc_access
    account.refresh_token = enc_refresh
    account.scope = granted_scope
    account.token_expiry = token_expiry
    # google_sub/email are intentionally left untouched: this gmail.readonly-only
    # client requests no identity scopes, so we don't have them here.

    db.commit()
    db.refresh(account)

    logger.info("Stored encrypted Gmail tokens for user %s", current_user.id)
    return ConnectionStatus(
        connected=True,
        scope=account.scope,
        connected_at=_iso(account.created_at),
    )


@router.get("/status", response_model=ConnectionStatus)
def gmail_connection_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConnectionStatus:
    """Report whether the user has a usable (refresh-token-bearing) connection.

    Never returns any token material -- only presence + scope + timestamp.
    """
    account = (
        db.query(GoogleAccount)
        .filter(GoogleAccount.user_id == current_user.id)
        .first()
    )
    connected = bool(account and account.refresh_token)
    return ConnectionStatus(
        connected=connected,
        scope=account.scope if connected else None,
        connected_at=_iso(account.created_at) if connected else None,
    )


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if isinstance(value, datetime) else None
