"""POST /events — client-side interaction telemetry into style_events.

Wave S0 Branch C. The frontend batches user actions that have no other server
round-trip (grid clicks, detail opens, region toggles, session bookends) and posts
them here. Server-derived events (gmail confirm, photo commit, PATCH edit/favorite)
do NOT come through this route — they are written inline in their handlers.

SECURITY / ABUSE GUARDS:
  * user_id is the JWT subject (get_current_user), NEVER the request body.
  * event_type is enum-validated; unknown types -> 422.
  * item_id (if present) must belong to the caller -> else 422 (no cross-user refs).
  * properties are size-capped + flattened (events_service._sanitize_properties).
  * batch size capped at settings.EVENTS_MAX_BATCH.
  * per-user sliding-window rate limit (in-process) -> 429 on burst.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dependencies import get_current_user, get_db
from app.models import User
from app.services.events_service import (
    EventValidationError,
    log_events,
    normalize_client_event,
    owned_item_ids_in,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])


# ---------------------------------------------------------------------------
# In-process per-user sliding-window rate limiter.
# Bounds POST /events ingestion per uvicorn worker. Not shared across workers /
# hosts — a Redis token bucket is the production upgrade. It fails OPEN only for
# the limiter's own bookkeeping, never for auth.
# ---------------------------------------------------------------------------
class _RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self._per_minute = per_minute
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, cost: int) -> bool:
        now = time.monotonic()
        window_start = now - 60.0
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] < window_start:
                hits.popleft()
            if len(hits) + cost > self._per_minute:
                return False
            for _ in range(cost):
                hits.append(now)
            # Opportunistic memory reclaim for idle users.
            if not hits:
                self._hits.pop(key, None)
            return True


_limiter = _RateLimiter(settings.EVENTS_RATE_LIMIT_PER_MINUTE)


class EventIn(BaseModel):
    """One client event. Extra keys are ignored; user_id can NEVER be set here."""

    eventType: str = Field(..., description="Taxonomy event type (enum-validated server-side)")
    itemId: Optional[str] = Field(None, description="UUID of a clothing item the caller owns")
    entityType: Optional[str] = None
    entityId: Optional[str] = None
    source: Optional[str] = None
    sessionId: Optional[str] = Field(None, description="Client session UUID")
    properties: Optional[Dict[str, Any]] = None

    class Config:
        extra = "ignore"


class EventBatchIn(BaseModel):
    events: List[EventIn] = Field(..., min_length=1)


class EventsAck(BaseModel):
    accepted: int


@router.post("", response_model=EventsAck, status_code=202)
def ingest_events(
    body: EventBatchIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EventsAck:
    """Accept a batch of client interaction events for the authenticated user."""
    if len(body.events) > settings.EVENTS_MAX_BATCH:
        raise HTTPException(
            status_code=422,
            detail=f"too many events (max {settings.EVENTS_MAX_BATCH} per request)",
        )

    if not _limiter.allow(str(current_user.id), len(body.events)):
        raise HTTPException(status_code=429, detail="event rate limit exceeded")

    raw_events = [e.model_dump() for e in body.events]

    # One ownership query for every referenced item id across the batch.
    referenced: set[UUID] = set()
    for e in raw_events:
        val = e.get("itemId")
        if val:
            try:
                referenced.add(UUID(str(val)))
            except (ValueError, TypeError):
                raise HTTPException(status_code=422, detail="itemId is not a valid UUID")
    owned = owned_item_ids_in(db, current_user.id, referenced)

    try:
        normalized = [
            normalize_client_event(
                e, db=db, user_id=current_user.id, owned_item_ids=owned
            )
            for e in raw_events
        ]
    except EventValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        count = log_events(db, current_user.id, normalized)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to persist %d events for user %s", len(normalized), current_user.id)
        raise HTTPException(status_code=500, detail="failed to record events")

    return EventsAck(accepted=count)
