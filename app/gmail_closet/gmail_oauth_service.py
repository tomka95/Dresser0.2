"""Gmail OAuth service for token management and client building.

Handles token refresh and provides authenticated Gmail API clients.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build, Resource
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.token_crypto import decrypt_token, encrypt_token
from app.models import GoogleAccount

logger = logging.getLogger(__name__)


def ensure_fresh_token(google_account: GoogleAccount, db: Session) -> str:
    """Ensure the GoogleAccount has a valid access token, refreshing if needed.

    Tokens are stored ENCRYPTED at rest (app/core/token_crypto). This function is
    the single place that decrypts them; the returned plaintext access token lives
    only in memory for the duration of a Gmail API call.

    Uses the dedicated GMAIL_OAUTH_* client (NOT the retired legacy GOOGLE_*).

    Args:
        google_account: GoogleAccount instance to check/refresh
        db: Database session for updating the token

    Returns:
        Valid (plaintext) access token string

    Raises:
        Exception: If token refresh fails
    """
    # Check if token is still valid (with 5 minute buffer)
    if google_account.token_expiry:
        # Ensure both datetimes are timezone-aware (UTC)
        now = datetime.now(timezone.utc)
        
        # Get token_expiry and ensure it's timezone-aware
        token_expiry = google_account.token_expiry
        # Convert naive datetime to UTC-aware if needed
        if token_expiry.tzinfo is None:
            # If naive, assume it's UTC and make it timezone-aware
            token_expiry = token_expiry.replace(tzinfo=timezone.utc)
        else:
            # If already timezone-aware, convert to UTC for comparison
            token_expiry = token_expiry.astimezone(timezone.utc)
        
        buffer = timedelta(minutes=5)
        expiry_with_buffer = now + buffer
        
        # Both should now be timezone-aware UTC, safe to compare
        if token_expiry > expiry_with_buffer:
            # Token is still valid -- decrypt the stored access token for use.
            return decrypt_token(google_account.access_token, field="access_token")

    # Token expired or expiring soon, refresh it
    logger.info(f"Refreshing access token for user {google_account.user_id}")

    if not google_account.refresh_token:
        raise ValueError("No refresh token available. User needs to re-authenticate.")

    refresh_token_plain = decrypt_token(google_account.refresh_token, field="refresh_token")

    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token_plain,
        "client_id": settings.GMAIL_OAUTH_CLIENT_ID,
        "client_secret": settings.GMAIL_OAUTH_CLIENT_SECRET,
    }
    
    try:
        response = httpx.post(
            token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        token_data = response.json()

        new_access_token = token_data["access_token"]

        # Re-encrypt before persisting; plaintext never reaches the DB.
        google_account.access_token = encrypt_token(new_access_token, field="access_token")
        google_account.token_expiry = datetime.now(timezone.utc) + timedelta(
            seconds=token_data.get("expires_in", 3600)
        )

        # Google sometimes returns a new refresh token (rotation).
        if "refresh_token" in token_data:
            google_account.refresh_token = encrypt_token(
                token_data["refresh_token"], field="refresh_token"
            )

        db.commit()
        db.refresh(google_account)

        logger.info(f"Successfully refreshed token for user {google_account.user_id}")
        return new_access_token

    except httpx.HTTPStatusError as e:
        # Never log the response body -- token-endpoint errors can echo token material.
        logger.error(f"Token refresh failed: HTTP {e.response.status_code}")
        raise Exception("Failed to refresh Google token.")
    except Exception as e:
        logger.error(f"Unexpected error during token refresh: {e}")
        raise


def get_gmail_client(google_account: GoogleAccount, db: Session) -> Resource:
    """Get an authenticated Gmail API client.
    
    Args:
        google_account: GoogleAccount instance with tokens
        db: Database session for token refresh if needed
        
    Returns:
        Authenticated Gmail API Resource
    """
    access_token = ensure_fresh_token(google_account, db)
    
    # Create credentials object
    credentials = Credentials(token=access_token)
    
    # Build and return Gmail client
    gmail = build("gmail", "v1", credentials=credentials)
    return gmail

