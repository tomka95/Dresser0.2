"""FastAPI router for Google OAuth authentication."""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
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
    user = db.query(User).filter(User.google_sub == google_sub).first()
    
    if not user:
        # Try to find by email if no user with this google_sub exists
        user = db.query(User).filter(User.email == email).first()
        
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
    db.refresh(user)
    
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
