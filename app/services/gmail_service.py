"""Gmail service for accessing Gmail API with stored Google OAuth tokens."""

import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx
from fastapi import HTTPException
from google.oauth2 import credentials as google_credentials
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import GoogleAccount

logger = logging.getLogger(__name__)


def get_google_account_for_user(db: Session, user_id) -> Optional[GoogleAccount]:
    """Get the GoogleAccount record for a given user.
    
    Args:
        db: Database session
        user_id: User UUID
        
    Returns:
        GoogleAccount instance if found, None otherwise
    """
    return db.query(GoogleAccount).filter(GoogleAccount.user_id == user_id).first()


def refresh_google_access_token(db: Session, google_account: GoogleAccount) -> GoogleAccount:
    """Refresh a Google access token using the refresh token.
    
    Args:
        db: Database session
        google_account: GoogleAccount instance with refresh_token
        
    Returns:
        Updated GoogleAccount instance with new access_token
        
    Raises:
        HTTPException: If refresh_token is missing or refresh fails
    """
    if not google_account.refresh_token:
        raise HTTPException(
            status_code=400,
            detail="No refresh token available. User needs to re-authorize Gmail access.",
        )
    
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "refresh_token": google_account.refresh_token,
        "grant_type": "refresh_token",
    }
    
    try:
        response = httpx.post(
            token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10.0,
        )
        response.raise_for_status()
        token_data = response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Google token refresh failed with status {e.response.status_code}: {e.response.text}")
        raise HTTPException(
            status_code=400,
            detail=f"Failed to refresh Google access token: {e.response.text}",
        )
    except Exception as e:
        logger.error(f"Unexpected error during token refresh: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error during token refresh: {str(e)}",
        )
    
    # Update the GoogleAccount with new token data
    google_account.access_token = token_data.get("access_token", google_account.access_token)
    
    expires_in = token_data.get("expires_in", 3600)
    google_account.token_expiry = datetime.utcnow() + timedelta(seconds=expires_in)
    
    # Update scope if provided
    if "scope" in token_data:
        google_account.scope = token_data["scope"]
    
    db.commit()
    db.refresh(google_account)
    
    logger.info(f"Successfully refreshed access token for user {google_account.user_id}")
    return google_account


def ensure_valid_google_access_token(db: Session, google_account: GoogleAccount) -> str:
    """Ensure the Google access token is valid, refreshing if necessary.
    
    Checks if the token is expired or about to expire (within 60 seconds),
    and refreshes it if needed.
    
    Args:
        db: Database session
        google_account: GoogleAccount instance
        
    Returns:
        Valid access token string
    """
    now = datetime.utcnow()
    buffer_seconds = 60  # Refresh if expiring within 60 seconds
    
    if google_account.token_expiry is None:
        # No expiry info, refresh to be safe
        logger.info("Token expiry is None, refreshing token")
        refresh_google_access_token(db, google_account)
        return google_account.access_token
    
    time_until_expiry = (google_account.token_expiry - now).total_seconds()
    
    if time_until_expiry < buffer_seconds:
        logger.info(f"Token expiring soon ({time_until_expiry:.0f}s), refreshing")
        refresh_google_access_token(db, google_account)
        return google_account.access_token
    
    return google_account.access_token


def get_gmail_service(access_token: str):
    """Create a Gmail API service object from an access token.
    
    Args:
        access_token: Google OAuth access token
        
    Returns:
        Gmail API service object
    """
    creds = google_credentials.Credentials(token=access_token)
    service = build("gmail", "v1", credentials=creds)
    return service









