"""Authenticated-user endpoint (`GET /auth/me`).

History: this module used to also expose `POST /auth/google`, a code->token
exchange that minted a legacy custom JWT and captured Gmail tokens. That endpoint
was RETIRED in the Gmail-connect cutover because it accepted a caller-supplied
`redirect_uri` (an open-redirect foot-gun) and duplicated identity handling that
now belongs entirely to Supabase Auth. Login is Supabase; Gmail authorization is
the dedicated /gmail/oauth/* flow. Only `/auth/me` remains here.
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.models import CalendarAccount, GoogleAccount, User

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)


@router.get("/me")
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get current authenticated user information.

    Returns:
        User info including gmail_sync_completed_at and the Gmail/Calendar
        connection flags. Folding the connection state in here lets the profile
        cards render their Active badge on first paint, instead of flashing the
        disconnected state while a separate /oauth/status round-trip lands.
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

    # Connection flags mirror the /gmail/oauth/status + /calendar/oauth/status
    # definition of "connected": an account row that carries a refresh token.
    gmail_account = (
        db.query(GoogleAccount).filter(GoogleAccount.user_id == current_user.id).first()
    )
    calendar_account = (
        db.query(CalendarAccount).filter(CalendarAccount.user_id == current_user.id).first()
    )

    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "display_name": current_user.display_name,
        "full_name": current_user.full_name,
        "avatar_url": current_user.avatar_url,
        "gmail_sync_completed_at": gmail_sync_completed_at,
        "gmail_connected": bool(gmail_account and gmail_account.refresh_token),
        "calendar_connected": bool(calendar_account and calendar_account.refresh_token),
    }
