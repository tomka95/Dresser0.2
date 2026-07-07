"""Authenticated outfit-image upload -> clothing pipeline (legacy multi-item flow).

Split out of main.py (P3.5, ARCHITECTURE_AUDIT R7): main.py is app assembly +
wiring only now; every route handler lives under app/api/routes/.

Superseded in the current web client by the photo-ingest detect/commit flow
(app/api/routes/photo_ingest.py), but kept live here (no behavior change) --
nothing calls this endpoint today, but nothing was asked to remove it either.
"""
import os
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.dependencies import get_current_user, get_db
from app.models import User
from app.services.clothing_pipeline import process_outfit_image
from app.services.outfit_db_service import save_outfit_results_to_db
from app.utils.image_validation import ImageValidationError, validate_and_sanitize
from app.utils.supabase_storage import SupabaseStorageClient

router = APIRouter(tags=["outfit-image"])


@router.post("/outfit-image")
async def upload_outfit_image_authenticated(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload an outfit image and process it through the clothing pipeline.

    This is a thin wrapper around the existing pipeline that uses the authenticated
    user from the verified access token instead of requiring user_id in the path.
    """
    # 1) Read + fully validate/sanitize the upload. The declared Content-Type is NOT
    #    trusted: validate_and_sanitize sniffs magic bytes, caps size, guards against
    #    decompression bombs + hostile dimensions, and STRIPS EXIF/GPS by re-encoding.
    #    Decode is CPU-bound → offload off the event loop. (Same front door as the
    #    Wave 1 photo-ingest path.)
    content = await file.read()
    try:
        sanitized = await run_in_threadpool(validate_and_sanitize, content)
    except ImageValidationError as e:
        msg = str(e)
        status = 413 if "file exceeds" in msg else 400
        raise HTTPException(status_code=status, detail=msg)

    # 2) Persist the SANITIZED bytes (EXIF-stripped) to a temp path; the suffix comes
    #    from the sniffed format, never the client-supplied filename.
    with tempfile.NamedTemporaryFile(delete=False, suffix=sanitized.suffix) as tmp:
        tmp.write(sanitized.data)
        temp_path = tmp.name

    # 4) Define output directory & JSON summary path for pipeline
    base_output_dir = os.path.join("outfit_outputs", str(current_user.id))
    images_output_dir = os.path.join(base_output_dir, "items")
    json_summary_path = os.path.join(base_output_dir, "summary.json")

    # 5) Run the clothing pipeline on the outfit image
    # We assume process_outfit_image is async and returns List[ItemResult]
    results = await process_outfit_image(
        outfit_image_path=temp_path,
        images_output_dir=images_output_dir,
        json_summary_path=json_summary_path,
    )

    # 6) Initialize Supabase storage client
    storage_client = SupabaseStorageClient.from_env()

    # 7) Save items + images + tags into DB
    created_items = save_outfit_results_to_db(
        db=db,
        user_id=current_user.id,
        results=results,
        storage_client=storage_client,
    )

    return {
        "user_id": str(current_user.id),
        "items_created": created_items,
    }
