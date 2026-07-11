"""Account lifecycle endpoints: irreversible deletion + GDPR data export.

Both are JWT-pinned to the CALLER: there is no target-user parameter, so a user
can only ever delete or export THEIR OWN account (the id comes from the verified
Supabase access token via ``get_current_user``). This is the App Store 5.1.1 /
GDPR requirement made real — the profile screen's previously-disabled buttons.

  * DELETE /account          — requires a typed confirmation string; erases the
                               account server-side (see app.services.account_deletion).
  * GET    /account/export   — returns one downloadable JSON of the user's data
                               (see app.services.account_export), no token material.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models import User
from app.services.account_deletion import delete_account
from app.services.account_export import build_account_export

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/account", tags=["account"])

# The exact phrase the client must echo back to confirm deletion. The account
# screen has the user type this (case-insensitive, trimmed) before the request is
# even sent; the server re-checks it so a stray/programmatic call can't erase an
# account without the explicit intent token.
_CONFIRMATION_PHRASE = "DELETE"


class DeleteAccountRequest(BaseModel):
    confirmation: str


class DeleteAccountResponse(BaseModel):
    deleted: bool = True


@router.delete("", response_model=DeleteAccountResponse)
def delete_my_account(
    body: DeleteAccountRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DeleteAccountResponse:
    """Permanently erase the authenticated user's account and all their data.

    Requires the typed confirmation phrase. Idempotent + resumable: on a partial
    failure the client can safely retry (see app.services.account_deletion).
    """
    if (body.confirmation or "").strip().upper() != _CONFIRMATION_PHRASE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Type {_CONFIRMATION_PHRASE} to confirm account deletion.",
        )

    delete_account(db, current_user.id)
    return DeleteAccountResponse(deleted=True)


@router.get("/export")
def export_my_account(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Return a downloadable JSON export of the authenticated user's data."""
    document = build_account_export(db, current_user)
    payload = json.dumps(document, indent=2, ensure_ascii=False)
    logger.info("Account-export served user=%s bytes=%d", current_user.id, len(payload))
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="tailor-data-export.json"'},
    )
