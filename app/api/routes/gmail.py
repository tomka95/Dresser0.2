"""FastAPI router for Gmail API endpoints."""

import logging
from typing import List, Dict, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.models import User
from app.services.gmail_service import (
    get_google_account_for_user,
    ensure_valid_google_access_token,
    get_gmail_service,
)
from app.services.email_clothing_service import save_email_items_for_user
from app.gmail_closet.pipeline import extract_items_from_gmail_oauth
from app.gmail_closet.models import Item

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/gmail",
    tags=["gmail"],
)


@router.get("/messages")
async def list_recent_messages(
    max_results: int = 10,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """List recent Gmail messages for the authenticated user.
    
    This endpoint:
    1. Fetches the user's GoogleAccount record
    2. Ensures the access token is valid (refreshes if needed)
    3. Calls Gmail API to list recent messages
    4. Returns simplified message data
    
    Args:
        max_results: Maximum number of messages to return (default: 10)
        current_user: Authenticated user from JWT
        db: Database session
        
    Returns:
        List of message dictionaries with id, snippet, subject, from fields
        
    Raises:
        HTTPException: If Gmail is not connected or API call fails
    """
    # Fetch GoogleAccount for the user
    google_account = get_google_account_for_user(db, current_user.id)
    
    if not google_account:
        raise HTTPException(
            status_code=400,
            detail="Gmail is not connected for this user. Please connect your Google account first.",
        )
    
    if not google_account.refresh_token:
        raise HTTPException(
            status_code=400,
            detail="Gmail is not connected for this user. Please reconnect your Google account with Gmail access.",
        )
    
    # Ensure we have a valid access token
    try:
        access_token = ensure_valid_google_access_token(db, google_account)
    except HTTPException as e:
        logger.error(f"Failed to get valid access token for user {current_user.id}: {e.detail}")
        raise HTTPException(
            status_code=400,
            detail="Failed to refresh Gmail access token. Please reconnect your Google account.",
        )
    
    # Build Gmail service
    try:
        service = get_gmail_service(access_token)
    except Exception as e:
        logger.error(f"Failed to build Gmail service for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to initialize Gmail service: {str(e)}",
        )
    
    # List messages
    try:
        messages_response = (
            service.users()
            .messages()
            .list(userId="me", maxResults=max_results)
            .execute()
        )
        
        messages = messages_response.get("messages", [])
        if not messages:
            return []
        
        # Fetch details for each message
        result = []
        for msg in messages:
            try:
                msg_detail = (
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=msg["id"],
                        format="metadata",
                        metadataHeaders=["Subject", "From"],
                    )
                    .execute()
                )
                
                # Extract headers
                headers = msg_detail.get("payload", {}).get("headers", [])
                subject = next((h["value"] for h in headers if h["name"] == "Subject"), None)
                from_addr = next((h["value"] for h in headers if h["name"] == "From"), None)
                
                result.append({
                    "id": msg["id"],
                    "snippet": msg_detail.get("snippet", ""),
                    "subject": subject,
                    "from": from_addr,
                })
            except Exception as e:
                logger.warning(f"Failed to fetch details for message {msg.get('id')}: {e}")
                # Continue with other messages even if one fails
                continue
        
        return result
        
    except Exception as e:
        logger.error(f"Gmail API call failed for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch Gmail messages: {str(e)}",
        )


@router.post("/clothing-items")
async def extract_clothing_from_gmail(
    max_years: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Extract clothing items from Gmail purchase emails using OAuth.
    
    This endpoint:
    1. Validates the user has a connected Google account with Gmail access
    2. Scans purchase emails from Gmail using the OAuth-based pipeline
    3. Extracts clothing items using the existing parsing logic
    4. Returns the list of items found
    
    Args:
        max_years: Optional limit on how far back to scan (default from config)
        current_user: Authenticated user from JWT
        db: Database session
        
    Returns:
        Dictionary with:
            - connected: bool (always True if successful)
            - items: List[Item] (clothing items found)
            
    Raises:
        HTTPException: If Gmail not connected or extraction fails
    """
   
    # Validate user has Google account with Gmail access
    if not current_user.google_account:
        raise HTTPException(
            status_code=400,
            detail="Gmail is not connected. Please sign in with Google first.",
        )
    
    if not current_user.google_account.refresh_token:
        raise HTTPException(
            status_code=400,
            detail="Gmail access not granted. Please reconnect with Gmail permissions.",
        )
    
    # TODO: Remove this debug logging
    
    try:
        # Run the OAuth-based pipeline
        items = await extract_items_from_gmail_oauth(
            user=current_user,
            db=db,
            max_years=max_years,
        )
        
        # Save items to database
        saved_items = save_email_items_for_user(
            db=db,
            user_id=current_user.id,
            items=items,
        )
        
        logger.info(f"Extracted {len(items)} items from Gmail, saved {len(saved_items)} new items to database for user {current_user.id}")
        
        return {
            "connected": True,
            "items": [item.dict() for item in items],
            "saved_count": len(saved_items),
        }
        
    except Exception as e:
        logger.error(f"Failed to extract clothing items for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to extract clothing items: {str(e)}",
        )




