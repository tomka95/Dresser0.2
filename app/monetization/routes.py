"""Monetization routes (Wave F1c): mint a click, then redirect through /out.

  POST /clicks          (auth) — record product_id + surface + user -> {clickId}.
  GET  /out/{click_id}  (public) — look up destination BY ID, 302 to wrapped/plain URL.

/out is deliberately UNAUTHENTICATED (a top-level browser navigation carries no bearer
token) and takes ONLY the opaque click_id path param. It NEVER accepts a destination URL
from the request — that is the whole open-redirect defense (the /auth/google lesson: no
client-supplied redirect targets). It is rate-limited per client IP.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models import User

from . import config
from .service import ClickValidationError, mint_click, resolve_destination

logger = logging.getLogger(__name__)

router = APIRouter(tags=["monetization"])


# ---------------------------------------------------------------------------
# Per-key sliding-window rate limiter (same pattern as POST /events).
# ---------------------------------------------------------------------------
class _RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self._per_minute = per_minute
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, cost: int = 1) -> bool:
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
            if not hits:
                self._hits.pop(key, None)
            return True


_limiter = _RateLimiter(config.click_rate_limit_per_minute())

# Query keys that would signal an open-redirect attempt — their presence is a hard 400.
_REDIRECT_PARAM_KEYS = frozenset({"url", "u", "dest", "destination", "target", "redirect", "r", "next", "to", "link"})


class ClickIn(BaseModel):
    productId: str = Field(..., description="UUID of the catalog product being clicked")
    surface: str = Field(..., description="feed | search | chat | deck")
    cardType: Optional[str] = Field(None, description="Card variant, e.g. product | outfit")

    class Config:
        extra = "ignore"


class ClickAck(BaseModel):
    clickId: str


@router.post("/clicks", response_model=ClickAck, status_code=201)
def create_click(
    body: ClickIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ClickAck:
    """Mint an opaque click_id for a product click. user_id is the JWT subject."""
    if not _limiter.allow(f"clicks:{current_user.id}"):
        raise HTTPException(status_code=429, detail="click rate limit exceeded")
    try:
        product_id = UUID(str(body.productId))
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="productId is not a valid UUID")
    try:
        click = mint_click(
            db, user_id=current_user.id, product_id=product_id,
            surface=body.surface, card_type=body.cardType,
        )
        db.commit()
    except ClickValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        db.rollback()
        logger.exception("failed to mint click for user %s", current_user.id)
        raise HTTPException(status_code=500, detail="failed to record click")
    return ClickAck(clickId=str(click.id))


@router.get("/out/{click_id}")
def out_redirect(click_id: str, request: Request, db: Session = Depends(get_db)):
    """Resolve a click BY ID and 302 to the (wrapped or plain) destination.

    Accepts NO destination from the caller: any redirect-target query param is a 400,
    and the URL is always read from our DB by click_id. Rate-limited per client IP.
    """
    # Open-redirect defense: reject any client-supplied redirect target outright.
    if any(k.lower() in _REDIRECT_PARAM_KEYS for k in request.query_params.keys()):
        raise HTTPException(status_code=400, detail="unexpected query parameter")

    client_ip = request.client.host if request.client else "unknown"
    if not _limiter.allow(f"out:{client_ip}"):
        raise HTTPException(status_code=429, detail="redirect rate limit exceeded")

    resolved = resolve_destination(db, click_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail="unknown or expired link")

    # 302 (temporary) so the wrap can change as programs get approved without caching.
    return RedirectResponse(url=resolved.wrapped_url, status_code=302)
