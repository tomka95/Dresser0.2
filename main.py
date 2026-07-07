"""Main FastAPI application for Tailor."""

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import check_database_connection
from app.api.routes import auth_google, chat, closet, gmail_oauth, gmail_ingest, photo_ingest, events, onboarding, outfit_feedback, shop
from app.monetization import routes as monetization_routes

import os
import tempfile

from app.models import User
from app.dependencies import get_db, get_current_user
from app.services.outfit_db_service import save_outfit_results_to_db
from app.utils.supabase_storage import SupabaseStorageClient
from app.services.clothing_pipeline import process_outfit_image
from app.utils.image_validation import validate_and_sanitize, ImageValidationError

# Database schema is owned exclusively by versioned Alembic migrations (see alembic/).
# The application never creates or mutates schema at startup. It only verifies that the
# configured database is reachable and fails loudly otherwise (no silent local fallback).

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast with a clear, actionable error if the configured DB is unreachable
    # or misconfigured, rather than silently degrading to a local/empty database.
    check_database_connection()
    logging.getLogger("uvicorn.error").info("Backend running at http://localhost:8000")
    yield


app = FastAPI(
    title="Tailor AI MVP",
    description="AI Closet / Stylist App",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS origins are env-driven (settings.cors_origins, from CORS_ALLOWED_ORIGINS).
# The localhost entries are a DEV-ONLY default; every shipped environment sets
# CORS_ALLOWED_ORIGINS to the real web origin(s). Origins are matched exactly —
# no wildcard is used alongside allow_credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Authentication endpoints
app.include_router(auth_google.router)

# Gmail-connect OAuth (gmail.readonly token plumbing; no ingestion)
app.include_router(gmail_oauth.router)

# Gmail receipt ingestion (phase 3b: fetch + filter + idempotency)
app.include_router(gmail_ingest.router)

# Photo -> closet ingestion (Wave 1: detect + cutout + stage; reuses the deck/confirm)
app.include_router(photo_ingest.router)

# Closet endpoints
app.include_router(closet.router)

# Interaction telemetry (Wave S0 Branch C: client-POSTed events -> style_events)
app.include_router(events.router)

# Onboarding seed (Wave S1: tap-only onboarding -> style_profiles/preferences/signals)
app.include_router(onboarding.router)

# AI Stylist chat (Wave S2: SSE agent over closet + Style Profile)
app.include_router(chat.router)

# Outfit feedback -> learning (Wave S3: reject/modify/worn -> preference_signals)
app.include_router(outfit_feedback.router)

# Shopping feed (Wave F2: closet-aware Stage-1 ranker -> GET /shop mixed cards)
app.include_router(shop.router)

app.include_router(monetization_routes.router)


@app.get("/health")
def health():
    return {"status": "ok"}


# NOTE: Legacy self-identifying / custom-auth endpoints were REMOVED in the
# auth-hardening pass (fix/auth-hardening, closes ARCHITECTURE_AUDIT S1/S2):
#   * POST /users and POST /users/{user_id}/clothing — unauthenticated writes that
#     trusted a client-supplied user_id (IDOR; ran on the RLS-bypassing owner
#     connection). No callers.
#   * POST /signup and POST /login — legacy custom HS256-JWT email/password auth.
#     Superseded entirely by Supabase Auth; no callers (the web client's legacy
#     auth clients were already removed).
# Identity is Supabase Auth ONLY: the authenticated user always comes from the
# verified access token (app/dependencies.get_current_user), never the path/body.
# The authenticated clothing-create path is the POST /closet router.


@app.post("/outfit-image")
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


if __name__ == "__main__":
    import threading
    import time
    import webbrowser

    import uvicorn

    # TODO: Remove this auto-open behavior before production.
    def open_swagger():
        # Give Uvicorn a moment to start
        time.sleep(1)
        webbrowser.open("http://localhost:8000/docs")

    threading.Thread(target=open_swagger, daemon=True).start()

    uvicorn.run(app, host="0.0.0.0", port=8000)
