"""FastAPI router for Gmail clothing extraction endpoint.

NOTE: This router is not automatically mounted in the main app.
To use it, import and mount it in your main FastAPI app:

    from app.gmail_closet import router as gmail_router
    app.include_router(gmail_router)
"""

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from .models import GmailCredentials, Item
from .pipeline import extract_items_from_gmail

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

