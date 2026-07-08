"""Main FastAPI application for Tailor.

App assembly + wiring only (P3.5, ARCHITECTURE_AUDIT R7): every route handler
lives under app/api/routes/ or app/monetization/routes.py. This module builds
the FastAPI app, configures CORS, includes routers, and (for local dev) runs
uvicorn -- no business logic.
"""

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db import check_database_connection
from app.api.routes import (
    auth_google,
    calendar,
    calendar_oauth,
    chat,
    closet,
    events,
    gmail_ingest,
    gmail_oauth,
    onboarding,
    outfit_feedback,
    outfit_image,
    photo_ingest,
    shop,
    todays_look,
    weather,
)
from app.monetization import routes as monetization_routes

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

# Today's Look (weather + calendar + profile -> one composed outfit + white grid
# collage on Home open; GET + remix + wear)
app.include_router(todays_look.router)

# Weather context (Open-Meteo -> read-through weather_cache -> GET /weather)
app.include_router(weather.router)

# Calendar-connect OAuth (calendar.events.readonly token plumbing) + live reads
app.include_router(calendar_oauth.router)
app.include_router(calendar.router)

app.include_router(monetization_routes.router)

# Authenticated multi-item outfit-image upload (legacy flow; see the router's
# own docstring for why it's kept separate from photo_ingest).
app.include_router(outfit_image.router)


@app.get("/health")
def health():
    return {"status": "ok"}


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
