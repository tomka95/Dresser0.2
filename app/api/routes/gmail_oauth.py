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
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.gmail_oauth_state import (
    _PURPOSE,
    _PURPOSE_ONBOARDING,
    OAuthStateError,
    issue_state,
    read_state_purpose,
)
from app.core.token_crypto import TokenCryptoError, decrypt_token, encrypt_token
from app.dependencies import get_current_user, get_db
from app.models import GoogleAccount, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gmail/oauth", tags=["gmail-oauth"])

_GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_GOOGLE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"


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
    onboarding: bool = False,
    current_user: User = Depends(get_current_user),
) -> StartResponse:
    """Build the Google consent URL for gmail.readonly, bound to this user.

    Uses the GMAIL_OAUTH_* client only, with access_type=offline + prompt=consent
    so Google returns a refresh token even on re-consent.

    ``onboarding=1`` mints a DISTINCT-purpose state so the exchange auto-starts a background
    receipt scan and the callback returns the user into onboarding (not /profile). The
    signed purpose is what gates the auto-scan — a plain-connect state can never trigger it.
    """
    _require_client_config()
    purpose = _PURPOSE_ONBOARDING if onboarding else _PURPOSE
    try:
        state = issue_state(str(current_user.id), purpose=purpose)
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
    # Set by /exchange when the connect used the onboarding purpose: the callback branches
    # its redirect on `onboarding`, and `sync_id` is the auto-started scan (None if a run
    # was already live / the inbox couldn't be scanned). /status leaves these at defaults.
    onboarding: bool = False
    sync_id: Optional[str] = None


@router.post("/exchange", response_model=ConnectionStatus)
def exchange_gmail_code(
    body: ExchangeRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConnectionStatus:
    """Validate state, exchange the auth code, store ENCRYPTED tokens, and — for an
    onboarding-purpose connect — auto-start the background receipt scan."""
    _require_client_config()

    # 1) CSRF + purpose: signature, freshness, and user-binding are verified here; the
    # returned purpose (plain-connect vs onboarding) is authenticated by the signature, so a
    # plain-connect state can never yield the onboarding purpose (and never auto-scan).
    try:
        purpose = read_state_purpose(body.state, expected_user_id=str(current_user.id))
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

    # 5) ONBOARDING auto-scan (Wave C / Fix 1): only when the signed purpose is onboarding,
    # kick the full receipt ingest in the BACKGROUND via the existing dual-path. Wrapped
    # defensively — a scan-start failure must NEVER fail the connect (the user is connected
    # regardless, and a later manual scan still works). Empty inbox -> the run completes with
    # zero candidates -> the Home banner never appears.
    is_onboarding = purpose == _PURPOSE_ONBOARDING
    scan_sync_id: Optional[str] = None
    if is_onboarding:
        try:
            from app.api.routes.gmail_ingest import maybe_start_onboarding_scan

            scan_sync_id = maybe_start_onboarding_scan(db, current_user.id, background_tasks)
        except Exception:  # noqa: BLE001 — connect must succeed even if the scan can't start
            logger.warning(
                "Onboarding auto-scan failed to start for user %s (connect succeeded)",
                current_user.id,
            )

    return ConnectionStatus(
        connected=True,
        scope=account.scope,
        connected_at=_iso(account.created_at),
        onboarding=is_onboarding,
        sync_id=scan_sync_id,
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


class DisconnectResponse(BaseModel):
    connected: bool = False


@router.post("/disconnect", response_model=DisconnectResponse)
def disconnect_gmail(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DisconnectResponse:
    """Revoke the grant at Google AND wipe the stored Gmail tokens (SCRUM-51).

    A verbatim mirror of the calendar disconnect. Best-effort revoke (a Google-side
    failure must not strand the user with an un-deletable row); the local token wipe is
    unconditional. IDEMPOTENT: no row -> already disconnected, returns success.

    Deletes ONLY the google_accounts token row. It deliberately does NOT touch
    already-ingested closet items or the processed_messages ledger — preserving that
    ledger is exactly what lets a later reconnect skip every previously-seen message
    instead of re-importing duplicates.
    """
    account = (
        db.query(GoogleAccount)
        .filter(GoogleAccount.user_id == current_user.id)
        .first()
    )
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
            logger.warning("Gmail token revoke call failed for user %s (wiping anyway)", current_user.id)

    db.delete(account)
    db.commit()
    logger.info("Disconnected Gmail for user %s", current_user.id)
    return DisconnectResponse(connected=False)


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if isinstance(value, datetime) else None
