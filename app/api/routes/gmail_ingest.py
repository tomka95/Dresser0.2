"""Gmail receipt ingestion endpoints.

POST /gmail/ingest/start      -- kick a full 2-year receipt sync (fetch → filter →
                                 extract → stage) for the authenticated user
GET  /gmail/ingest/status     -- poll progress by sync_id (fetched/filtered/extracted)
GET  /gmail/ingest/candidates -- the user's status='pending' candidates for the swipe deck
POST /gmail/ingest/confirm    -- accept/reject/edit candidates; accepts UPSERT to the closet

The sync work runs in a background thread (Starlette runs sync BackgroundTasks in a
thread pool) and now runs the FULL pipeline through extraction. The candidates/confirm
endpoints run inline in the request. No email content is logged. clothing_items are
written ONLY via /confirm.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.gmail_closet.fetch_service import ingest_background
from app.gmail_closet.review_service import (
    ConfirmError,
    confirm_candidates,
    list_pending_candidates,
)
from app.gmail_closet.usage import get_user_cost_summary
from app.models import GoogleAccount, IngestRun, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gmail/ingest", tags=["gmail-ingest"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class StartIngestResponse(BaseModel):
    sync_id: str


class IngestProgress(BaseModel):
    fetched: int
    filtered: int
    extracted: int
    total_estimate: Optional[int] = None


class IngestStatusResponse(BaseModel):
    sync_id: str
    status: str
    progress: IngestProgress
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class CandidateSource(BaseModel):
    merchant: Optional[str] = None
    order_id: Optional[str] = None
    message_id: Optional[str] = None
    google_account_id: Optional[int] = None
    email_date: Optional[str] = None


class CandidateOut(BaseModel):
    candidate_id: str
    name: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    color: Optional[str] = None
    size: Optional[str] = None
    qty: int = 1
    unit_price: Optional[float] = None
    currency: Optional[str] = None
    order_date: Optional[str] = None
    is_return: bool = False
    image_url: Optional[str] = None
    # Image lifecycle for the streaming deck (Phase 4): resolved | pending | placeholder.
    # 'pending' -> still resolving (shimmer + keep polling); 'placeholder' -> slow tiers
    # exhausted (static placeholder, stop polling); 'resolved' -> image_url is present.
    image_status: Optional[str] = None
    confidence_overall: Optional[float] = None
    # Fields the UI should flag for edit (null value or weak per-field confidence).
    low_confidence_fields: List[str] = Field(default_factory=list)
    seen_count: int = 1
    source: CandidateSource


class ConfirmRequest(BaseModel):
    """A swipe-review decision. candidate_ids are validated to belong to the caller.

    edits maps a candidate_id (which MUST also appear in `accepted`) to a
    {field: value} patch applied before the closet write.
    """
    accepted: List[str] = Field(default_factory=list)
    rejected: List[str] = Field(default_factory=list)
    edits: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class ConfirmWrittenItem(BaseModel):
    clothing_item_id: str
    candidate_id: str
    name: str
    inserted: bool   # True = new closet row; False = dedup update (ON CONFLICT)


class ConfirmResponse(BaseModel):
    accepted_count: int
    rejected_count: int
    inserted_count: int   # new clothing_items rows
    updated_count: int    # existing rows updated via UNIQUE(user_id, source_line_key)
    written: List[ConfirmWrittenItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/start", response_model=StartIngestResponse)
def start_ingest(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StartIngestResponse:
    """Kick a 2-year Gmail receipt sync for the authenticated user.

    Returns {sync_id} immediately; the sync runs in a background thread.
    Poll GET /gmail/ingest/status?sync_id=<id> for progress.
    """
    account = (
        db.query(GoogleAccount)
        .filter(GoogleAccount.user_id == current_user.id)
        .first()
    )
    if not account or not account.refresh_token:
        raise HTTPException(
            status_code=400,
            detail="Gmail not connected. Complete /gmail/oauth/start first.",
        )

    # Prevent duplicate concurrent syncs for the same user
    running = (
        db.query(IngestRun)
        .filter(
            IngestRun.user_id == current_user.id,
            IngestRun.status == "running",
        )
        .first()
    )
    if running:
        raise HTTPException(
            status_code=409,
            detail=f"A sync is already running: sync_id={running.sync_id}",
        )

    sync_id = uuid.uuid4()
    run = IngestRun(sync_id=sync_id, user_id=current_user.id, status="running")
    db.add(run)
    db.commit()

    # Starlette routes sync BackgroundTasks through run_in_threadpool — safe to block.
    background_tasks.add_task(
        ingest_background,
        str(current_user.id),
        str(sync_id),
    )

    logger.info("sync_id=%s: ingest scheduled for user=%s", sync_id, current_user.id)
    return StartIngestResponse(sync_id=str(sync_id))


@router.get("/status", response_model=IngestStatusResponse)
def get_ingest_status(
    sync_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IngestStatusResponse:
    """Return current status and progress for a sync run.

    Only the authenticated user can query their own runs (user_id filter).
    """
    run = (
        db.query(IngestRun)
        .filter(
            IngestRun.sync_id == sync_id,
            IngestRun.user_id == current_user.id,
        )
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Sync run not found.")

    return IngestStatusResponse(
        sync_id=str(run.sync_id),
        status=run.status,
        progress=IngestProgress(
            fetched=run.fetched_count,
            filtered=run.filtered_count,
            extracted=run.extracted_count,
            total_estimate=run.total_estimate,
        ),
        started_at=run.started_at.isoformat() if run.started_at else None,
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
    )


@router.get("/candidates", response_model=List[CandidateOut])
def get_ingest_candidates(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[CandidateOut]:
    """Return the authenticated user's status='pending' candidates for the swipe deck.

    User-scoped via the JWT (explicit user_id filter; RLS is defense-in-depth). Phase 4
    ordering: image-present cards first, then still-resolving (imageless) ones, each
    group most-confident first. Each candidate carries image_status so the deck can show
    a shimmer while resolution is in flight and poll this endpoint until nothing is
    pending. low_confidence_fields flags weak/null fields for inline edit.
    """
    return list_pending_candidates(db, current_user.id)


@router.get("/usage")
def get_ingest_usage(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Per-user cost rollup for the AUTHENTICATED caller (self-serve read path).

    Returns totals across all the user's syncs + a per-sync breakdown, split by tier
    (extraction / vision-verify / shopping search). Counts + dollars only — no email
    content. For "what has an arbitrary user X cost us", ops use
    `python -m scripts.dev_user_cost <email>` (this route is intentionally self-only;
    there is no admin auth layer to safely expose other users here).
    """
    return get_user_cost_summary(db, current_user.id)


@router.post("/confirm", response_model=ConfirmResponse)
def confirm_ingest_candidates(
    body: ConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConfirmResponse:
    """Apply accept/reject/edit decisions for the authenticated user.

    Accepted candidates have their edits applied and UPSERT into clothing_items on
    UNIQUE(user_id, source_line_key) — re-confirming never duplicates. Rejected
    candidates write nothing. user_id is always the JWT subject; every candidate_id is
    validated to belong to the caller (cross-user / unknown ids -> 400).
    """
    try:
        result = confirm_candidates(
            db,
            current_user.id,
            accepted=body.accepted,
            rejected=body.rejected,
            edits=body.edits,
        )
    except ConfirmError as exc:
        # ConfirmError messages name only ids/fields — safe to surface, no email content.
        raise HTTPException(status_code=400, detail=str(exc))

    return ConfirmResponse(
        accepted_count=result.accepted_count,
        rejected_count=result.rejected_count,
        inserted_count=result.inserted_count,
        updated_count=result.updated_count,
        written=[
            ConfirmWrittenItem(
                clothing_item_id=w.clothing_item_id,
                candidate_id=w.candidate_id,
                name=w.name,
                inserted=w.inserted,
            )
            for w in result.written
        ],
    )
