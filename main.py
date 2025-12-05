"""Main FastAPI application for Dresser."""

import logging
from typing import Optional
from uuid import UUID

from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import Base, engine
from app.models import User, ClothingItem
from app.dependencies import get_db
from app.security import hash_password, verify_password
from app.gmail_closet import router as gmail_router

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Dresser AI MVP",
    description="AI Closet / Stylist App",
    version="0.2.0",
)

# Enable INFO-level logging globally
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Gmail clothing extraction endpoints (for Dresser MVP)
app.include_router(gmail_router)


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
def signup(email: str, password: str, db: Session = Depends(get_db)):
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

    return {"id": str(user.id), "email": user.email}


@app.post("/login")
def login(email: str, password: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Later we will return a JWT or session token here.
    return {"id": str(user.id), "email": user.email}



########################
from app.db import SessionLocal
from app.models import User

def db_check():
    db = SessionLocal()
    try:
        # try a simple query
        users = db.query(User).limit(5).all()
        print("Connected to Supabase! Found", len(users), "users")
    finally:
        db.close()
###########################################

if __name__ == "__main__":
    import threading
    import time
    import webbrowser

    import uvicorn

    db_check()

    # TODO: Remove this auto-open behavior before production.
    def open_swagger():
        # Give Uvicorn a moment to start
        time.sleep(1)
        webbrowser.open("http://localhost:8000/docs")

    threading.Thread(target=open_swagger, daemon=True).start()

    uvicorn.run(app, host="0.0.0.0", port=8000)
