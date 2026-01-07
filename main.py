"""Main FastAPI application for Tailor."""

import logging
from typing import Optional
from uuid import UUID

from fastapi import FastAPI, Depends, HTTPException, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.db import Base, engine
from app.security import hash_password, verify_password, create_access_token
from app.api.routes import auth_google, closet

import os
import tempfile

from app.models import User, ClothingItem
from app.dependencies import get_db, get_current_user
from app.services.outfit_db_service import save_outfit_results_to_db
from app.utils.supabase_storage import SupabaseStorageClient
from app.services.clothing_pipeline import process_outfit_image

# This project does not currently use Alembic for migrations.

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Tailor AI MVP",
    description="AI Closet / Stylist App",
    version="0.2.0",
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

# Enable INFO-level logging globally
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


# Authentication endpoints
app.include_router(auth_google.router)

# Closet endpoints
app.include_router(closet.router)


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
def signup(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")

    user = User(
        email=email,
        hashed_password=hash_password(password),
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
    # 1) Validate file
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing file")
    
    # Validate MIME type
    ALLOWED_MIME_TYPES = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed types: {', '.join(ALLOWED_MIME_TYPES)}"
        )
    
    # 2) Read file content and validate size
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File size exceeds maximum allowed size of {MAX_FILE_SIZE / 1024 / 1024}MB"
        )
    
    # 3) Save uploaded file to a temporary path
    suffix = os.path.splitext(file.filename)[1] or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
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


@app.post("/users/{user_id}/outfit-image")
async def upload_outfit_image(
    user_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    # 1) Validate user
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 2) Save uploaded file to a temporary path
    suffix = os.path.splitext(file.filename)[1] or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        temp_path = tmp.name

    # 3) Define output directory & JSON summary path for pipeline
    base_output_dir = os.path.join("outfit_outputs", str(user_id))
    images_output_dir = os.path.join(base_output_dir, "items")
    json_summary_path = os.path.join(base_output_dir, "summary.json")

    # 4) Run the clothing pipeline on the outfit image
    # We assume process_outfit_image is async and returns List[ItemResult]
    results = await process_outfit_image(
        outfit_image_path=temp_path,
        images_output_dir=images_output_dir,
        json_summary_path=json_summary_path,
    )

    # 5) Initialize Supabase storage client
    storage_client = SupabaseStorageClient.from_env()

    # 6) Save items + images + tags into DB
    created_items = save_outfit_results_to_db(
        db=db,
        user_id=user_id,
        results=results,
        storage_client=storage_client,
    )

    return {
        "user_id": str(user_id),
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
