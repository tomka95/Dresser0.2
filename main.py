"""Main FastAPI application for Dresser."""

import logging

from fastapi import FastAPI

from app.gmail_closet import router as gmail_router

app = FastAPI(
    title="Dresser API",
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

