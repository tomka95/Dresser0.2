"""FastAPI router for Google OAuth authentication."""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.exc import ProgrammingError
from sqlalchemy import text

from app.core.config import settings
from app.dependencies import get_db, get_current_user
from app.models import User, GoogleAccount
from app.security import create_access_token

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)


class GoogleCallbackRequest(BaseModel):
    code: str
    redirect_uri: Optional[str] = None


@router.post("/google")
async def google_callback(
    request: GoogleCallbackRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Handle Google OAuth callback and exchange authorization code for tokens.
    
    This endpoint:
    1. Exchanges the authorization code for access/refresh tokens
    2. Fetches user info from Google
    3. Creates or updates User and GoogleAccount records
    4. Returns JWT token and Google tokens to the frontend
    
    Args:
        request: Request body containing the OAuth authorization code
        db: Database session
        
    Returns:
        Dictionary with:
            - access_token: JWT token for API authentication
            - refresh_token: Google refresh token (if provided)
            - user: User information
    """
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        logger.error("Google OAuth credentials not configured")
        raise HTTPException(
            status_code=500,
            detail="Google OAuth is not configured on the server",
        )
    
    # Exchange authorization code for tokens
    token_url = "https://oauth2.googleapis.com/token"
    
    # Use redirect_uri from request, or from settings, or default
    # The redirect_uri MUST match exactly what was used in the authorization request
    redirect_uri = (
        request.redirect_uri 
        or settings.GOOGLE_REDIRECT_URI 
        or "http://localhost:3000/google/callback"
    )
    
    logger.info(f"Exchanging Google code with redirect_uri: {redirect_uri}")
    
    token_data = {
        "code": request.code,
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    
    try:
        response = httpx.post(
            token_url,
            data=token_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10.0,
        )
        response.raise_for_status()
        token_response = response.json()
    except httpx.HTTPStatusError as e:
        error_text = e.response.text
        logger.error(f"Failed to exchange Google code: {e.response.status_code} - {error_text}")
        
        # Try to parse Google's error response for more details
        try:
            error_json = e.response.json()
            error_detail = error_json.get("error_description", error_json.get("error", "Unknown error"))
        except:
            error_detail = error_text or "Failed to exchange authorization code with Google"
        
        raise HTTPException(
            status_code=400,
            detail=f"Failed to exchange authorization code: {error_detail}",
        )
    except Exception as e:
        logger.error(f"Unexpected error during token exchange: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error during authentication: {str(e)}",
        )
    
    access_token = token_response.get("access_token")
    refresh_token = token_response.get("refresh_token")
    expires_in = token_response.get("expires_in", 3600)
    scope = token_response.get("scope", "")
    
    if not access_token:
        raise HTTPException(
            status_code=400,
            detail="No access token received from Google",
        )
    
    # Fetch user info from Google
    userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
    try:
        userinfo_response = httpx.get(
            userinfo_url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )
        userinfo_response.raise_for_status()
        userinfo = userinfo_response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Failed to fetch user info: {e.response.status_code} - {e.response.text}")
        raise HTTPException(
            status_code=400,
            detail="Failed to fetch user information from Google",
        )
    except Exception as e:
        logger.error(f"Unexpected error fetching user info: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error fetching user information: {str(e)}",
        )
    
    google_sub = userinfo.get("id")
    email = userinfo.get("email")
    name = userinfo.get("name")
    picture = userinfo.get("picture")
    
    if not google_sub or not email:
        raise HTTPException(
            status_code=400,
            detail="Invalid user information from Google",
        )
    
    # Find or create User
    # Handle missing migration gracefully - if column doesn't exist, use raw SQL fallback
    user = None
    migration_missing = False
    
    try:
        user = db.query(User).filter(User.google_sub == google_sub).first()
    except ProgrammingError as e:
        error_str = str(e)
        if "gmail_sync_completed_at" in error_str or "UndefinedColumn" in error_str:
            logger.error("Migration missing: users.gmail_sync_completed_at - OAuth flow will continue but sync status cannot be tracked. Please run migration: migrations/add_gmail_sync_completed_at.sql")
            migration_missing = True
            # Use raw SQL to check if user exists
            result = db.execute(
                text("SELECT id FROM users WHERE google_sub = :google_sub"),
                {"google_sub": google_sub}
            ).first()
            if result:
                # User exists - load by ID with a workaround (will fail but we'll handle it)
                try:
                    user = db.get(User, result[0])
                except ProgrammingError:
                    # Even get() fails, so we'll need to work around this
                    # For now, treat as user not found and will create new (will fail on unique constraint)
                    logger.warning("Cannot load existing user due to missing migration - will attempt to create/update")
                    user = None
        else:
            raise
    
    if not user:
        # Try to find by email if no user with this google_sub exists
        try:
            user = db.query(User).filter(User.email == email).first()
        except ProgrammingError as e:
            error_str = str(e)
            if "gmail_sync_completed_at" in error_str or "UndefinedColumn" in error_str:
                if not migration_missing:
                    logger.error("Migration missing: users.gmail_sync_completed_at - OAuth flow will continue but sync status cannot be tracked. Please run migration: migrations/add_gmail_sync_completed_at.sql")
                migration_missing = True
                # Use raw SQL to check if user exists by email
                result = db.execute(
                    text("SELECT id FROM users WHERE email = :email"),
                    {"email": email}
                ).first()
                if result:
                    try:
                        user = db.get(User, result[0])
                    except ProgrammingError:
                        logger.warning("Cannot load existing user due to missing migration")
                        user = None
            else:
                raise
        
        if user:
            # Update existing user with google_sub
            user.google_sub = google_sub
        else:
            # Create new user - this will work even without migration (INSERT won't include missing column)
            user = User(
                email=email,
                google_sub=google_sub,
                display_name=name,
                full_name=name,
                avatar_url=picture,
                hashed_password="",  # No password for OAuth users
            )
            db.add(user)
            try:
                db.flush()  # Flush to get user.id
            except ProgrammingError as e:
                if "gmail_sync_completed_at" in str(e) or "UndefinedColumn" in str(e):
                    # Even INSERT might reference the column in some cases
                    # Try to work around by not setting the attribute
                    logger.warning("User creation may fail due to missing migration - attempting workaround")
                    # Remove the attribute if it was set
                    if hasattr(user, 'gmail_sync_completed_at'):
                        delattr(user, 'gmail_sync_completed_at')
                    db.flush()
                else:
                    raise
        
        if user:
            # Update existing user with google_sub
            user.google_sub = google_sub
        else:
            # Create new user
            user = User(
                email=email,
                google_sub=google_sub,
                display_name=name,
                full_name=name,
                avatar_url=picture,
                hashed_password="",  # No password for OAuth users
            )
            db.add(user)
            db.flush()  # Flush to get user.id
    
    # Update user info if available
    if name and not user.full_name:
        user.full_name = name
    if picture and not user.avatar_url:
        user.avatar_url = picture
    if name and not user.display_name:
        user.display_name = name
    
    # Create or update GoogleAccount
    google_account = db.query(GoogleAccount).filter(GoogleAccount.user_id == user.id).first()
    
    token_expiry = datetime.utcnow() + timedelta(seconds=expires_in)
    
    if google_account:
        # Update existing GoogleAccount
        google_account.google_sub = google_sub
        google_account.email = email
        google_account.access_token = access_token
        google_account.token_expiry = token_expiry
        google_account.scope = scope
        if refresh_token:
            google_account.refresh_token = refresh_token
    else:
        # Create new GoogleAccount
        google_account = GoogleAccount(
            user_id=user.id,
            google_sub=google_sub,
            email=email,
            access_token=access_token,
            refresh_token=refresh_token,
            scope=scope,
            token_expiry=token_expiry,
        )
        db.add(google_account)
    
    db.commit()
    # Refresh user - handle missing migration gracefully
    try:
        db.refresh(user)
    except ProgrammingError as e:
        error_str = str(e)
        if "gmail_sync_completed_at" in error_str or "UndefinedColumn" in error_str:
            logger.warning("Cannot refresh user due to missing migration - continuing without refresh")
            # User object is still usable, just not refreshed from DB
        else:
            raise
    
    # Create JWT token for the user
    jwt_token = create_access_token(data={"sub": str(user.id)})
    
    logger.info(f"Successfully authenticated user {user.id} via Google OAuth")
    
    return {
        "access_token": jwt_token,
        "refresh_token": refresh_token,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "full_name": user.full_name,
            "avatar_url": user.avatar_url,
        },
    }


@router.get("/me")
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get current authenticated user information.
    
    Returns:
        User info including gmail_sync_completed_at
    """
    # Safely access gmail_sync_completed_at - handle missing column gracefully
    gmail_sync_completed_at = None
    try:
        sync_at = getattr(current_user, 'gmail_sync_completed_at', None)
        if sync_at:
            gmail_sync_completed_at = sync_at.isoformat()
    except (AttributeError, ProgrammingError) as e:
        if "gmail_sync_completed_at" in str(e) or "UndefinedColumn" in str(e):
            logger.warning("Migration missing: users.gmail_sync_completed_at - returning null for sync status")
            gmail_sync_completed_at = None
        else:
            raise
    
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "display_name": current_user.display_name,
        "full_name": current_user.full_name,
        "avatar_url": current_user.avatar_url,
        "gmail_sync_completed_at": gmail_sync_completed_at,
    }
