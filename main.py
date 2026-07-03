"""Main FastAPI application for Tailor."""

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from contextlib import asynccontextmanager
from typing import Optional
from uuid import UUID

from fastapi import FastAPI, Depends, HTTPException, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.db import check_database_connection
from app.security import hash_password, verify_password, create_access_token
from app.api.routes import auth_google, closet, gmail_oauth, gmail_ingest, photo_ingest, events

import os
import tempfile

from app.models import User, ClothingItem
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

# Configure CORS to allow frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Next.js dev server
        "http://127.0.0.1:3000",
    ],
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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/users")
def create_user(
    email: str,
    display_name: Optional[str] = None,
    db: Session = Depends(get_db),
):
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")

    user = User(email=email, display_name=display_name)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": str(user.id), "email": user.email}


@app.post("/users/{user_id}/clothing")
def create_clothing_item(
    user_id: UUID,
    name: str,
    category: Optional[str] = None,
    sub_category: Optional[str] = None,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    item = ClothingItem(
        user_id=user_id,
        name=name,
        category=category,
        sub_category=sub_category,
    )

    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": str(item.id), "name": item.name}


@app.post("/signup")
def signup(email: str = Form(...), password: str = Form(...), full_name: Optional[str] = Form(None), db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")

    user = User(
        email=email,
        hashed_password=hash_password(password),
        display_name=full_name if full_name else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Create JWT token for the new user
    jwt_token = create_access_token(data={"sub": str(user.id)})
    
    return {
        "access_token": jwt_token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "email": user.email,
        },
    }


@app.post("/login")
def login(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Create JWT token for the user
    jwt_token = create_access_token(data={"sub": str(user.id)})
    
    return {
        "access_token": jwt_token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "email": user.email,
        },
    }


@app.post("/outfit-image")
async def upload_outfit_image_authenticated(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload an outfit image and process it through the clothing pipeline.
    
    This is a thin wrapper around the existing pipeline that uses the authenticated
    user from JWT token instead of requiring user_id in the path.
    
    Returns the same response structure as POST /users/{user_id}/outfit-image.
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

    # Return same structure as /users/{user_id}/outfit-image
    return {
        "user_id": str(current_user.id),
        "items_created": created_items,
    }


# NOTE: The legacy POST /users/{user_id}/outfit-image endpoint was REMOVED. It was
# unauthenticated (anyone could upload to any user_id in the path) and ran ZERO upload
# validation. It had no callers — the web client uses the authenticated POST /outfit-image
# (which pins the user to the JWT), and the pipeline is exercised in tests via
# process_outfit_image() directly. Deleting it removes the attack surface outright.


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
