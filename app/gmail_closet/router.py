"""FastAPI router for Gmail clothing extraction endpoint.

NOTE: This router is not automatically mounted in the main app.
To use it, import and mount it in your main FastAPI app:

    from app.gmail_closet import router as gmail_router
    app.include_router(gmail_router)
"""

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .models import GmailCredentials, Item
from .pipeline import extract_items_from_gmail, _process_emails
from .oauth_client import create_oauth_flow, get_gmail_service, fetch_purchase_emails_via_api

router = APIRouter(
    prefix="/api/v1/gmail",
    tags=["gmail-clothing"],
)


@router.post("/clothing-items")
async def get_clothing_items_from_gmail(creds: GmailCredentials) -> Dict[str, Any]:
    """Extract clothing items from Gmail purchase emails.

    Returns:
        {
          "connected": true,
          "items": [Item, Item, ...]
        }
    """
    try:
        items = await extract_items_from_gmail(creds)
        return {
            "connected": True,
            "items": items,
        }
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.get("/auth/start")
async def start_gmail_oauth(redirect_uri: str = "http://localhost:3000/gmail/callback"):
    """Start OAuth flow for Gmail access."""
    try:
        flow = create_oauth_flow(redirect_uri)
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true'
        )
        return {
            "authorization_url": authorization_url,
            "state": state
        }
    except Exception as ex:
        raise HTTPException(status_code=500, detail=str(ex))


class OAuthCallbackRequest(BaseModel):
    code: str
    state: str


@router.post("/auth/callback")
async def handle_gmail_oauth_callback(request: OAuthCallbackRequest):
    """Handle OAuth callback and exchange code for tokens."""
    try:
        flow = create_oauth_flow("http://localhost:3000/gmail/callback")
        flow.fetch_token(code=request.code)
        
        credentials = flow.credentials
        
        # Return credentials to store on frontend
        return {
            "access_token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": credentials.scopes
        }
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


class OAuthCredentials(BaseModel):
    credentials: dict
    max_years: int | None = None


@router.post("/extract-with-oauth")
async def extract_clothing_with_oauth(request: OAuthCredentials):
    """Extract clothing items using OAuth credentials instead of app password.
    
    Uses the same extraction pipeline as the IMAP endpoint for consistent results.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"Received OAuth extraction request with credentials keys: {request.credentials.keys()}")
        
        # Build Gmail API service
        service = get_gmail_service(request.credentials)
        
        # Fetch purchase-like emails via Gmail API
        logger.info("Fetching emails via Gmail API...")
        email_data = fetch_purchase_emails_via_api(service, request.max_years)
        logger.info(f"Fetched {len(email_data)} emails")
        
        # Process emails through the SAME pipeline as IMAP
        items = _process_emails(email_data)
        
        logger.info(f"Extracted {len(items)} unique clothing items")
        
        return {
            "connected": True,
            "items": items
        }
    except Exception as ex:
        logger.error(f"Error extracting clothing: {type(ex).__name__}: {str(ex)}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(ex))

