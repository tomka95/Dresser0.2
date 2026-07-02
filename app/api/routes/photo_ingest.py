"""Photo -> closet ingestion endpoints (Wave 1.5: interactive region selection).

POST /photo/ingest/detect  -- upload one or more photos; garments are detected and
                              the regions persisted in a transient
                              photo_detect_sessions row. NOTHING is staged or stored:
                              no cutouts, no storage writes, no ledger rows. The
                              source photo is never persisted anywhere.

POST /photo/ingest/commit  -- re-upload the SAME files plus a selections JSON; each
                              file binds to its session by sha256 and only the
                              SELECTED regions (plus user-drawn manual boxes) are cut
                              out and STAGED as ingest_candidates.

This is the photo SOURCE's entry point. It deliberately reuses the generic spine for
everything after staging: the swipe deck reads GET /gmail/ingest/candidates and the
user confirms via POST /gmail/ingest/confirm exactly as for Gmail. Progress is a real
ingest_runs row (created at commit), pollable at GET /gmail/ingest/status?sync_id=…

SECURITY: user_id is the authenticated caller (get_current_user / JWT), NEVER the
request body. Every uploaded image is validated + EXIF-stripped (image_validation)
before it is hashed or sent to the model. Sync endpoints (run in Starlette's
threadpool) so the blocking detect/crop work doesn't block the event loop. Logs carry
hashes + counts only — never image bytes, masks, or filenames.
"""
from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models import User
from app.photo_closet.ingest_service import (
    PhotoSelection,
    PhotoSelectionInvalid,
    PhotoSessionConflict,
    PhotoSessionExpired,
    PhotoSessionNotFound,
    run_photo_commit,
    run_photo_detect,
)
from app.utils.image_validation import (
    ImageValidationError,
    SanitizedImage,
    validate_and_sanitize,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/photo/ingest", tags=["photo-ingest"])

# Bound the work per request (each photo is a Gemini detect call + N crops).
MAX_PHOTOS_PER_REQUEST = 10


# --- Response shapes ----------------------------------------------------------

class RegionConfidenceOut(BaseModel):
    name: Optional[float] = None
    category: Optional[float] = None
    color: Optional[float] = None
    pattern: Optional[float] = None
    material: Optional[float] = None
    fit: Optional[float] = None
    brand: Optional[float] = None


class RegionOut(BaseModel):
    """One detected region as shown to the client. NO mask — masks stay server-side
    in the session row and are only read back at commit for the cutout."""

    region_id: int
    box_2d: List[int]
    name: str
    category: str
    color: Optional[str] = None
    pattern: Optional[str] = None
    material: Optional[str] = None
    fit: Optional[str] = None
    brand: Optional[str] = None
    confidence_overall: Optional[float] = None
    confidence: RegionConfidenceOut = RegionConfidenceOut()


class PhotoDetectSessionOut(BaseModel):
    session_id: Optional[str]  # None => duplicate photo (no session created)
    filename: str              # echo of the uploaded file's name, for client mapping
    image_sha256: str
    width: int
    height: int
    duplicate: bool
    person_count: int
    regions: List[RegionOut] = []


class PhotoDetectResponse(BaseModel):
    sessions: List[PhotoDetectSessionOut]  # same order as the uploaded files


class PhotoIngestStartResponse(BaseModel):
    """Commit response. Shape kept identical to the Wave-1 /start response for client
    compat; held_multi_person is always 0 now (multi-person photos flow through
    detect and the user disambiguates by selecting regions)."""

    sync_id: str
    images_processed: int   # photos whose selection was staged
    staged: int             # garment candidates staged for review
    duplicates: int         # photos skipped as already-committed duplicates
    held_multi_person: int  # always 0 (kept for client compat)
    message: Optional[str] = None


# --- Shared request plumbing ----------------------------------------------------

def _sanitize_uploads(files: List[UploadFile]) -> List[SanitizedImage]:
    """Validate + sanitize ALL uploads up front: magic-byte sniff, size/dimension/
    bomb guard, EXIF/GPS strip. Rejects the request on the first bad file."""
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")
    if len(files) > MAX_PHOTOS_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files (max {MAX_PHOTOS_PER_REQUEST} per request).",
        )
    sanitized: List[SanitizedImage] = []
    for f in files:
        raw = f.file.read()
        try:
            sanitized.append(validate_and_sanitize(raw))
        except ImageValidationError as exc:
            msg = str(exc)
            code = 413 if "limit" in msg and "MB" in msg else 400
            raise HTTPException(status_code=code, detail=f"{f.filename or 'image'}: {msg}")
    return sanitized


def _parse_selections(selections_raw: str) -> List[PhotoSelection]:
    """Parse + structurally validate the commit `selections` form field (JSON).

    Deep semantic validation (region ids exist, box geometry) happens in the service
    against the session rows; this guards shape only. Any malformation -> 400.
    """
    def _bad(detail: str) -> HTTPException:
        return HTTPException(status_code=400, detail=f"Malformed selections: {detail}")

    try:
        payload = json.loads(selections_raw)
    except (json.JSONDecodeError, TypeError):
        raise _bad("not valid JSON")
    if not isinstance(payload, list) or not payload:
        raise _bad("expected a non-empty JSON array")

    parsed: List[PhotoSelection] = []
    for entry in payload:
        if not isinstance(entry, dict):
            raise _bad("each selection must be an object")
        session_id = entry.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise _bad("each selection needs a session_id string")
        region_ids = entry.get("selected_region_ids", [])
        if not isinstance(region_ids, list) or any(
            isinstance(v, bool) or not isinstance(v, int) for v in region_ids
        ):
            raise _bad("selected_region_ids must be a list of integers")
        manual_boxes = entry.get("manual_boxes", [])
        if not isinstance(manual_boxes, list):
            raise _bad("manual_boxes must be a list of boxes")
        parsed.append(PhotoSelection(
            session_id=session_id,
            selected_region_ids=region_ids,
            manual_boxes=manual_boxes,
        ))
    return parsed


# --- Endpoints --------------------------------------------------------------------

@router.post("/detect", response_model=PhotoDetectResponse)
def detect_photo_regions(
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PhotoDetectResponse:
    """Detect garment regions in the uploaded photos for the authenticated user.

    Returns one session per non-duplicate photo (same order as the files) holding
    the detected regions for the client's picker. Persists NOTHING except the
    transient session rows — the photos themselves are never stored.
    """
    sanitized = _sanitize_uploads(files)

    outcomes = run_photo_detect(db, current_user.id, sanitized)

    sessions = [
        PhotoDetectSessionOut(
            session_id=o.session_id,
            filename=f.filename or "image",
            image_sha256=o.image_sha256,
            width=o.width,
            height=o.height,
            duplicate=o.duplicate,
            person_count=o.person_count,
            regions=[RegionOut(**r) for r in o.regions],
        )
        for f, o in zip(files, outcomes)
    ]
    return PhotoDetectResponse(sessions=sessions)


@router.post("/commit", response_model=PhotoIngestStartResponse)
def commit_photo_selection(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    selections: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PhotoIngestStartResponse:
    """Stage the SELECTED regions from re-uploaded photos.

    ``selections`` is a JSON array: [{session_id, selected_region_ids: [int],
    manual_boxes: [[ymin,xmin,ymax,xmax]]}]. Each file binds to its session by
    sha256. Staged candidates are then reviewed through the shared deck/confirm path.
    """
    sanitized = _sanitize_uploads(files)
    parsed_selections = _parse_selections(selections)

    sanitized_by_sha: Dict[str, SanitizedImage] = {s.sha256: s for s in sanitized}

    # Storage is optional: if the bucket isn't configured the run still stages
    # candidates (image_url null) rather than 500ing.
    storage_client = None
    try:
        from app.utils.supabase_storage import SupabaseStorageClient

        storage_client = SupabaseStorageClient.from_env()
    except Exception as exc:  # missing S3 env / client init failure
        logger.warning("photo commit: storage unavailable, staging without images: %s", exc)

    # Only run background generation when it CAN complete: storage to persist the card
    # AND a provider + verify key configured. Otherwise finalize the run at commit and
    # leave candidates as raw cutouts (unchanged behavior when generation isn't set up).
    from app.photo_closet.generation_service import generate_background, generation_armed

    will_generate = storage_client is not None and generation_armed()

    try:
        result = run_photo_commit(
            db, current_user.id, storage_client, sanitized_by_sha, parsed_selections,
            defer_completion=will_generate,
        )
    except PhotoSessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PhotoSessionExpired as exc:
        raise HTTPException(status_code=410, detail=str(exc))
    except PhotoSessionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except PhotoSelectionInvalid as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Kick the background generation job (own DB session; Starlette threadpool). Gated on
    # staged>0 to match run_photo_commit's defer condition, so the run is never left
    # 'running' with no job to finalize it. Returns immediately with sync_id.
    if will_generate and result.staged > 0:
        background_tasks.add_task(
            generate_background, str(current_user.id), result.sync_id,
        )

    message = None
    if result.staged == 0 and result.duplicates:
        message = "Already imported — nothing new to review."
    elif result.staged == 0:
        message = "No regions were selected — nothing was imported."

    return PhotoIngestStartResponse(
        sync_id=result.sync_id,
        images_processed=result.images_processed,
        staged=result.staged,
        duplicates=result.duplicates,
        held_multi_person=0,
        message=message,
    )
