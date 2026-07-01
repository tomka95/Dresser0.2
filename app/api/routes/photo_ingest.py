"""Photo -> closet ingestion endpoint (Wave 1).

POST /photo/ingest/start  -- upload one or more photos of yourself; each garment is
                             detected, cut out, and STAGED as an ingest_candidate.

This is the photo SOURCE's entry point. It deliberately reuses the generic spine for
everything after staging: the swipe deck reads GET /gmail/ingest/candidates and the
user confirms via POST /gmail/ingest/confirm exactly as for Gmail. Progress is a real
ingest_runs row, pollable at GET /gmail/ingest/status?sync_id=…

SECURITY: user_id is the authenticated caller (get_current_user / JWT), NEVER the
request body. Every uploaded image is validated + EXIF-stripped (image_validation)
before it is hashed, stored, or sent to the model. A sync endpoint (run in Starlette's
threadpool) so the blocking detect/crop work doesn't block the event loop.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models import User
from app.photo_closet.ingest_service import ingest_photos
from app.utils.image_validation import (
    ImageValidationError,
    SanitizedImage,
    validate_and_sanitize,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/photo/ingest", tags=["photo-ingest"])

# Bound the work per request (each photo is a Gemini detect call + N crops).
MAX_PHOTOS_PER_REQUEST = 10


class PhotoIngestStartResponse(BaseModel):
    sync_id: str
    images_processed: int   # photos that ran detect+stage
    staged: int             # garment candidates staged for review
    duplicates: int         # photos skipped as exact/near duplicates
    held_multi_person: int  # photos skipped: more than one person detected
    message: Optional[str] = None


@router.post("/start", response_model=PhotoIngestStartResponse)
def start_photo_ingest(
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PhotoIngestStartResponse:
    """Validate + ingest uploaded photos for the authenticated user.

    Returns immediately-computed counts (processing is inline). Staged candidates are
    then reviewed through the shared deck/confirm path. Invalid images are rejected
    BEFORE any are processed, so a bad file fails the whole request loudly.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")
    if len(files) > MAX_PHOTOS_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files (max {MAX_PHOTOS_PER_REQUEST} per request).",
        )

    # Validate + sanitize ALL up front: magic-byte sniff, size/dimension/bomb guard,
    # EXIF/GPS strip. Reject the request on the first bad file.
    sanitized: List[SanitizedImage] = []
    for f in files:
        raw = f.file.read()
        try:
            sanitized.append(validate_and_sanitize(raw))
        except ImageValidationError as exc:
            msg = str(exc)
            code = 413 if "limit" in msg and "MB" in msg else 400
            raise HTTPException(status_code=code, detail=f"{f.filename or 'image'}: {msg}")

    # Storage is optional: if the bucket isn't configured the run still stages
    # candidates (image_url null) rather than 500ing.
    storage_client = None
    try:
        from app.utils.supabase_storage import SupabaseStorageClient

        storage_client = SupabaseStorageClient.from_env()
    except Exception as exc:  # missing S3 env / client init failure
        logger.warning("photo ingest: storage unavailable, staging without images: %s", exc)

    result = ingest_photos(
        db, current_user.id, sanitized, storage_client=storage_client,
    )

    message = None
    if result.held_multi_person:
        message = (
            f"{result.held_multi_person} photo(s) had more than one person and were "
            "skipped — upload a photo of just yourself."
        )
    elif result.staged == 0 and result.duplicates:
        message = "Already imported — nothing new to review."
    elif result.staged == 0:
        message = "No clothing detected in the photo(s)."

    return PhotoIngestStartResponse(
        sync_id=result.sync_id,
        images_processed=result.images_processed,
        staged=result.staged,
        duplicates=result.duplicates,
        held_multi_person=result.held_multi_person,
        message=message,
    )
