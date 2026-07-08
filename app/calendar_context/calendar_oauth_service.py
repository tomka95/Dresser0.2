"""Calendar OAuth token management + client building.

Mirrors app/gmail_closet/gmail_oauth_service.py: the single place that decrypts
the stored calendar tokens, refreshes the access token when stale (rotating the
refresh token if Google returns a new one), and hands back an authenticated
Google Calendar API client. Uses the dedicated CALENDAR_OAUTH_* client.

Token material exists in plaintext only transiently in memory here; it is
re-encrypted (app/core/token_crypto, same key + per-field AAD as Gmail) before it
ever touches the DB, and never logged.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.token_crypto import decrypt_token, encrypt_token
from app.models import CalendarAccount

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://oauth2.googleapis.com/token"


def ensure_fresh_token(account: CalendarAccount, db: Session) -> str:
    """Return a valid plaintext access token, refreshing + persisting if stale.

    NOTE ON SESSIONS: this commits on ``db``, so callers on the RLS-scoped agent
    transaction must pass a SEPARATE owner session (see stylist.calendar) rather
    than the turn's connection — committing mid-turn would end that transaction.
    """
    if account.token_expiry:
        expiry = account.token_expiry
        expiry = expiry.replace(tzinfo=timezone.utc) if expiry.tzinfo is None else expiry.astimezone(timezone.utc)
        if expiry > datetime.now(timezone.utc) + timedelta(minutes=5):
            return decrypt_token(account.access_token, field="access_token")

    if not account.refresh_token:
        raise ValueError("No calendar refresh token; user must reconnect.")

    refresh_plain = decrypt_token(account.refresh_token, field="refresh_token")
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_plain,
        "client_id": settings.CALENDAR_OAUTH_CLIENT_ID,
        "client_secret": settings.CALENDAR_OAUTH_CLIENT_SECRET,
    }
    try:
        resp = httpx.post(
            _TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10.0,
        )
        resp.raise_for_status()
        token_data = resp.json()
    except httpx.HTTPStatusError as exc:
        # Never log the body — token-endpoint errors can echo token material.
        logger.error("Calendar token refresh failed: HTTP %s", exc.response.status_code)
        raise Exception("Failed to refresh Google Calendar token.")

    new_access = token_data["access_token"]
    account.access_token = encrypt_token(new_access, field="access_token")
    account.token_expiry = datetime.now(timezone.utc) + timedelta(
        seconds=token_data.get("expires_in", 3600)
    )
    if "refresh_token" in token_data:  # rotation
        account.refresh_token = encrypt_token(token_data["refresh_token"], field="refresh_token")

    db.commit()
    db.refresh(account)
    logger.info("Refreshed calendar token for user %s", account.user_id)
    return new_access


def get_calendar_client(account: CalendarAccount, db: Session) -> Resource:
    """Authenticated Google Calendar v3 API client."""
    access_token = ensure_fresh_token(account, db)
    credentials = Credentials(token=access_token)
    return build("calendar", "v3", credentials=credentials)
