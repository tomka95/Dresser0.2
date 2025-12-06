"""FastAPI router for Google OAuth authentication."""

import logging
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dependencies import get_db
from app.models import User, GoogleAccount
from app.security import create_access_token

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)


class GoogleAuthRequest(BaseModel):
    """Request model for Google OAuth authorization code."""

    code: str


class GoogleAuthResponse(BaseModel):
    """Response model for Google OAuth authentication."""

    access_token: str
    token_type: str
    user: dict
    has_gmail_access: bool


@router.post("/google", response_model=GoogleAuthResponse)
async def google_auth(
    request: GoogleAuthRequest,
    db: Session = Depends(get_db),
) -> GoogleAuthResponse:
    """Handle Google OAuth login and Gmail access token storage.

    This endpoint:
    1. Exchanges the authorization code with Google for tokens
    2. Verifies the id_token and extracts user info
    3. Creates or updates the User and GoogleAccount records
    4. Returns a JWT access token and user info

    Args:
        request: Request containing the Google authorization code
        db: Database session

    Returns:
        GoogleAuthResponse with JWT token and user info

    Raises:
        HTTPException: If authentication fails or Google returns an error
    """
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Google OAuth is not configured. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        )

    # Step 1: Exchange authorization code for tokens
    token_response = await _exchange_code_for_tokens(request.code)

    id_token_str = token_response.get("id_token")
    access_token = token_response.get("access_token")
    refresh_token = token_response.get("refresh_token")
    expires_in = token_response.get("expires_in", 3600)
    scope = token_response.get("scope", "")

    if not id_token_str or not access_token:
        raise HTTPException(
            status_code=400,
            detail="Invalid token response from Google: missing id_token or access_token",
        )

    # Step 2: Verify id_token and extract user info
    try:
        user_info = _verify_and_extract_user_info(id_token_str)
    except ValueError as e:
        logger.error(f"Failed to verify Google id_token: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid Google token: {str(e)}")

    google_sub = user_info.get("sub")
    email = user_info.get("email")
    name = user_info.get("name")
    picture = user_info.get("picture")

    if not email:
        raise HTTPException(status_code=400, detail="Google token missing email claim")

    # Step 3: Upsert User
    user = _upsert_user(db, google_sub, email, name, picture)

    # Step 4: Upsert GoogleAccount
    google_account = _upsert_google_account(
        db,
        user.id,
        google_sub,
        email,
        access_token,
        refresh_token,
        scope,
        expires_in,
    )

    # Step 5: Create our JWT token
    jwt_token = create_access_token(data={"sub": str(user.id)})

    return GoogleAuthResponse(
        access_token=jwt_token,
        token_type="bearer",
        user={
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "avatar_url": user.avatar_url,
        },
        has_gmail_access=google_account.refresh_token is not None,
    )


async def _exchange_code_for_tokens(code: str) -> dict:
    """Exchange Google authorization code for tokens.

    Args:
        code: Authorization code from Google

    Returns:
        Dictionary with tokens from Google

    Raises:
        HTTPException: If token exchange fails
    """
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "code": code,
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Google token exchange failed with status {e.response.status_code}: {e.response.text}")
        raise HTTPException(
            status_code=400,
            detail=f"Google token exchange failed: {e.response.text}",
        )
    except Exception as e:
        logger.error(f"Unexpected error during token exchange: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error during token exchange: {str(e)}",
        )


def _verify_and_extract_user_info(id_token_str: str) -> dict:
    """Verify Google id_token and extract user information.

    Args:
        id_token_str: JWT id_token from Google

    Returns:
        Dictionary with user info (sub, email, name, picture)

    Raises:
        ValueError: If token verification fails
    """
    try:
        request_obj = google_requests.Request()
        idinfo = id_token.verify_oauth2_token(
            id_token_str,
            request_obj,
            settings.GOOGLE_CLIENT_ID,
        )
        return idinfo
    except ValueError as e:
        logger.error(f"Google id_token verification failed: {e}")
        raise


def _upsert_user(
    db: Session,
    google_sub: str,
    email: str,
    name: Optional[str],
    picture: Optional[str],
) -> User:
    """Create or update a User record.

    Args:
        db: Database session
        google_sub: Google user ID (sub claim)
        email: User email
        name: User full name (optional)
        picture: User avatar URL (optional)

    Returns:
        User instance
    """
    # Try to find existing user by google_sub or email
    user = db.query(User).filter(User.google_sub == google_sub).first()
    if not user:
        user = db.query(User).filter(User.email == email).first()

    if not user:
        # Create new user
        user = User(
            email=email,
            google_sub=google_sub,
            full_name=name,
            avatar_url=picture,
            hashed_password="",  # OAuth users don't have passwords
        )
        db.add(user)
    else:
        # Update existing user (don't overwrite non-null with null)
        if google_sub and not user.google_sub:
            user.google_sub = google_sub
        if name and not user.full_name:
            user.full_name = name
        elif name:
            user.full_name = name  # Update if new name provided
        if picture and not user.avatar_url:
            user.avatar_url = picture
        elif picture:
            user.avatar_url = picture  # Update if new picture provided

    db.commit()
    db.refresh(user)
    return user


def _upsert_google_account(
    db: Session,
    user_id: UUID,
    google_sub: str,
    email: str,
    access_token: str,
    refresh_token: Optional[str],
    scope: Optional[str],
    expires_in: int,
) -> GoogleAccount:
    """Create or update a GoogleAccount record.

    Args:
        db: Database session
        user_id: User UUID
        google_sub: Google user ID
        email: User email
        access_token: Google access token
        refresh_token: Google refresh token (optional)
        scope: OAuth scope string
        expires_in: Token expiration in seconds

    Returns:
        GoogleAccount instance
    """
    google_account = db.query(GoogleAccount).filter(GoogleAccount.user_id == user_id).first()

    token_expiry = datetime.utcnow() + timedelta(seconds=expires_in)

    if not google_account:
        # Create new GoogleAccount
        google_account = GoogleAccount(
            user_id=user_id,
            google_sub=google_sub,
            email=email,
            access_token=access_token,
            refresh_token=refresh_token,
            scope=scope,
            token_expiry=token_expiry,
        )
        db.add(google_account)
    else:
        # Update existing GoogleAccount
        google_account.access_token = access_token
        google_account.scope = scope
        google_account.token_expiry = token_expiry
        # Only update refresh_token if Google provided a new one
        if refresh_token:
            google_account.refresh_token = refresh_token
        # Update email and google_sub if they changed
        google_account.email = email
        google_account.google_sub = google_sub

    db.commit()
    db.refresh(google_account)
    return google_account

