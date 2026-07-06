"""GET /shop — the Stage-1 shopping feed (Wave F2).

Returns a page of ranked, mixed cards for the authenticated user: ~70% product cards
("unlocks N outfits" + gap preview) and ~30% outfit cards (owned items + 1 buyable, via the
composer + a PIL collage). Ranked by app.ranking (taste + wardrobe-gap + price_fit +
quality − fatigue), re-ranked for diversity/calibration with an exploration slice, and
paginated by a session watermark so pages of one browse stay consistent.

Feed serve is $0 API (pgvector + numpy + the pure assembler — no model call).

MONETIZATION BOUNDARY: cards carry a productId, never an outbound/affiliate URL. To open a
product the client mints a click via POST /clicks and follows GET /out/{click_id}
(app/monetization). This route imports nothing from app.monetization.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dependencies import get_current_user, get_db
from app.models import User
from app.ranking.feed import build_feed

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shop", tags=["shop"])


class ShopFeedResponse(BaseModel):
    """A page of the feed. ``cards`` is a heterogeneous list (product | outfit); each card
    carries feedPosition / cardType / exploration for the client's event capture. ``sessionId``
    is the watermark the client MUST echo on the next page for a stable feed."""

    cards: List[Dict[str, Any]] = Field(default_factory=list)
    cursor: int
    sessionId: str
    hasMore: bool
    framing: str  # "personalized" | "starter_looks"
    diagnostics: Dict[str, Any] = Field(default_factory=dict)


@router.get("", response_model=ShopFeedResponse)
def get_shop_feed(
    cursor: int = Query(0, ge=0, description="Offset of the page to return (0 = first)."),
    sessionId: Optional[str] = Query(
        None, description="Session watermark from a prior page; omit on the first request."
    ),
    pageSize: Optional[int] = Query(
        None, ge=1, le=100, description="Cards per page (defaults to the configured page size)."
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ShopFeedResponse:
    # New browse → mint a watermark (randomness here is fine; the ranker itself is seeded
    # deterministically FROM this value so pagination is reproducible).
    session_id = sessionId or uuid.uuid4().hex

    page = build_feed(
        db,
        current_user.id,
        session_id=session_id,
        cursor=cursor,
        page_size=pageSize,
    )
    return ShopFeedResponse(
        cards=page.cards,
        cursor=page.cursor,
        sessionId=page.session_id,
        hasMore=page.has_more,
        framing=page.framing,
        diagnostics=page.diagnostics,
    )
