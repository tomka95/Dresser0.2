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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dependencies import get_current_user, get_db
from app.gmail_closet.fetch_service import ingest_background
from app.gmail_closet.review_service import (
    ConfirmError,
    confirm_candidates,
    dismiss_candidate,
    list_pending_candidates,
    retry_candidate,
    settle_counts,
)
from app.platform.jobs import enqueue
from app.platform.usage import get_user_cost_summary
from app.models import GoogleAccount, IngestCandidate, IngestRun, User
from app.services.events_service import EventValidationError, log_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gmail/ingest", tags=["gmail-ingest"])


def _log_confirm_events(db: Session, user_id, body: "ConfirmRequest", result) -> None:
    """Server-derive style_events for a review-deck confirm (accept/reject/edit).

    Best-effort and isolated: any telemetry failure is swallowed and rolled back
    so it can never fail an already-successful closet write.
    """
    try:
        # candidate_id -> written clothing_item_id (accepted rows only).
        item_by_candidate = {w.candidate_id: w.clothing_item_id for w in result.written}
        for candidate_id in body.accepted:
            log_event(
                db,
                user_id=user_id,
                event_type="save",
                item_id=item_by_candidate.get(candidate_id),
                entity_type="ingest_candidate",
                entity_id=candidate_id,
                source="review_deck",
            )
        for candidate_id in body.rejected:
            log_event(
                db,
                user_id=user_id,
                event_type="dismiss",
                entity_type="ingest_candidate",
                entity_id=candidate_id,
                source="review_deck",
            )
        for candidate_id, patch in body.edits.items():
            for field in patch.keys():
                log_event(
                    db,
                    user_id=user_id,
                    event_type="edit_field",
                    item_id=item_by_candidate.get(candidate_id),
                    entity_type="ingest_candidate",
                    entity_id=candidate_id,
                    source="review_deck",
                    properties={"field": str(field)},
                )
        db.commit()
    except (EventValidationError, Exception):
        db.rollback()
        logger.warning("confirm telemetry failed for user %s (write already committed)", user_id, exc_info=True)


# ---------------------------------------------------------------------------
# Shared ingest dispatch (reused by POST /start and the onboarding OAuth exchange)
# ---------------------------------------------------------------------------

def _dispatch_ingest_run(
    db: Session, user_id: UUID, background_tasks: BackgroundTasks, *, trigger: str
) -> str:
    """Create the IngestRun and dispatch the sync via the EXISTING dual-path. Returns sync_id.

    Flag ON -> enqueue a durable gmail_ingest job in the SAME transaction as the run (the
    flip is the ONLY change needed for prod-grade recovery — SCRUM-66). Flag OFF (current
    default) -> a Starlette BackgroundTask. ``trigger`` ('onboarding' | 'manual') is stamped
    on the run so Home can find onboarding scans. ids-only payload (no tokens/PII)."""
    sync_id = uuid.uuid4()
    run = IngestRun(sync_id=sync_id, user_id=user_id, status="running", trigger=trigger)
    db.add(run)
    if settings.JOBS_GMAIL_INGEST_ENABLED:
        job = enqueue(
            db,
            type="gmail_ingest",
            user_id=user_id,
            payload={"user_id": str(user_id), "sync_id": str(sync_id)},
            max_attempts=settings.JOBS_MAX_ATTEMPTS,
        )
        run.job_id = job.id
        db.commit()
        logger.info("sync_id=%s: ingest enqueued job=%s user=%s trigger=%s",
                    sync_id, job.id, user_id, trigger)
    else:
        db.commit()
        background_tasks.add_task(ingest_background, str(user_id), str(sync_id))
        logger.info("sync_id=%s: ingest scheduled user=%s trigger=%s", sync_id, user_id, trigger)
    return str(sync_id)


def maybe_start_onboarding_scan(
    db: Session, user_id: UUID, background_tasks: BackgroundTasks
) -> Optional[str]:
    """Auto-start a background receipt scan on the onboarding Gmail connect. Never raises.

    Idempotent + 409-guarded: if a run is already 'running' for this user, reuse it (return
    its sync_id) rather than double-start. Requires a stored refresh token (the exchange
    just wrote one). A failure here must NEVER fail the OAuth connect, so the caller wraps
    this defensively — connect succeeds even if the scan couldn't start."""
    account = (
        db.query(GoogleAccount).filter(GoogleAccount.user_id == user_id).first()
    )
    if not account or not account.refresh_token:
        return None
    running = (
        db.query(IngestRun)
        .filter(IngestRun.user_id == user_id, IngestRun.status == "running")
        .first()
    )
    if running:
        return str(running.sync_id)  # already scanning -> don't double-start
    return _dispatch_ingest_run(db, user_id, background_tasks, trigger="onboarding")


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class StartIngestResponse(BaseModel):
    sync_id: str


class PendingReviewOut(BaseModel):
    """The Home "review N items ready" banner payload. pending=False -> show nothing."""
    pending: bool = False
    sync_id: Optional[str] = None
    ready_count: int = 0


class AckReviewRequest(BaseModel):
    sync_id: str
    action: str = Field("opened", description="'opened' (user tapped through) | 'dismissed'")


class IngestProgress(BaseModel):
    fetched: int
    filtered: int
    extracted: int
    total_estimate: Optional[int] = None
    # Wave 2 product-image generation progress (photo runs; 0 for Gmail). While a photo
    # run is generating, status stays 'running' with generation_ready climbing toward
    # generation_total — enough to drive the add-photo "Preparing N items -> Review
    # ready" pill. generation_failed counts cards held for a later retry sweep.
    generation_total: int = 0
    generation_ready: int = 0
    generation_failed: int = 0
    # Photo-seam Phase 3 — THE whole-batch settle, straight from the shared
    # review_service.settle_counts. `settled` is the authoritative "review may
    # surface" signal (all pending candidates terminal or needs-size);
    # needs_size counts verified cards held only by a missing size.
    settled: bool = False
    needs_size: int = 0


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
    # Wave 2 generation card + lifecycle (photo only; null for Gmail). The deck renders
    # generated_image_url as the product card once generation_status='ready', keeps a
    # progress state while 'generating', and keeps polling until it is no longer null/
    # 'generating'. image_url stays the raw crop (verify reference + fallback).
    generated_image_url: Optional[str] = None
    generation_status: Optional[str] = None
    confidence_overall: Optional[float] = None
    # Fields the UI should flag for edit (null value or weak per-field confidence).
    low_confidence_fields: List[str] = Field(default_factory=list)
    seen_count: int = 1
    # Ingestion source: 'gmail' | 'photo'. Drives the source-aware deck badge.
    source_type: str = "gmail"
    # Ready-first Phase 1 (additive): the fail-closed person tri-state and the
    # authoritative readiness state. The deck only ever receives pipeline_state='ready'
    # rows, but the fields are surfaced for observability/debug UI.
    on_model: bool = False
    person_status: str = "unknown"
    pipeline_state: str = "staged"
    # Soft, OPTIONAL 'add size' affordance (size is never a gate — Fix 1).
    needs_size: bool = False
    # Fix 2 — a candidate the deck shows: 'ready' (a normal card) | 'failed' (a
    # 'couldn't process this item' entry: no image, a reason, Retry/Dismiss).
    review_state: str = "ready"
    failure_reason: Optional[str] = None
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

    # Create + dispatch via the shared dual-path (flag ON -> durable job; OFF ->
    # BackgroundTask). trigger='manual' distinguishes this from the onboarding auto-scan.
    sync_id = _dispatch_ingest_run(db, current_user.id, background_tasks, trigger="manual")
    return StartIngestResponse(sync_id=sync_id)


@router.get("/status", response_model=IngestStatusResponse)
def get_ingest_status(
    sync_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IngestStatusResponse:
    """Return current status and progress for a sync run.

    Only the authenticated user can query their own runs (user_id filter).

    Photo-seam Phase 3: the response carries the WHOLE-BATCH settle (the same shared
    condition the Home banner uses), and polling a COMPLETED-but-unsettled photo run
    strand-kills: stale 'generating' residue (a crashed background pass) is demoted to
    'pending_retry', and a debounced self-heal is dispatched so the settle condition
    is always reachable without waiting for the user's next upload.
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

    counts = settle_counts(db, current_user.id, str(run.sync_id))
    if (
        run.source_type in ("photo", "manual")
        and run.status != "running"
        and not counts.settled
    ):
        _kick_photo_strand_heal(
            db, current_user.id, str(run.sync_id), background_tasks,
            source_type=run.source_type,
        )

    return IngestStatusResponse(
        sync_id=str(run.sync_id),
        status=run.status,
        progress=IngestProgress(
            fetched=run.fetched_count,
            filtered=run.filtered_count,
            extracted=run.extracted_count,
            total_estimate=run.total_estimate,
            generation_total=run.generation_total or 0,
            generation_ready=run.generation_ready or 0,
            generation_failed=run.generation_failed or 0,
            settled=counts.settled,
            needs_size=counts.needs_size,
        ),
        started_at=run.started_at.isoformat() if run.started_at else None,
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
    )


# Poll-kick debounce: at most one strand-heal dispatch per user per window, per
# process. In-memory on purpose (BackgroundTasks mode is single-process; the durable
# worker path has its own stale-reclaim) — a lost debounce merely re-dispatches an
# idempotent, budget-capped sweep.
_HEAL_KICK_WINDOW_S = 60.0
_heal_kick_last: Dict[str, float] = {}


def _kick_photo_strand_heal(
    db: Session, user_id, sync_id: str, background_tasks: BackgroundTasks,
    *, source_type: str = "photo",
) -> None:
    """Strand-killer for a completed-but-unsettled photo/manual batch (Phase 3/4).

    (1) Stale 'generating' residue — a background pass that died mid-candidate (the
        run is no longer running, so nothing owns these rows) — is demoted to
        'pending_retry' so the sweep can re-select it.
    (2) A debounced background re-attempt: photo runs get the self-heal sweep
        (this user's 'pending_retry' residue including this sync); manual runs get
        their idempotent per-sync generation pass re-run.
    No-ops when generation isn't armed (the sweep couldn't succeed and would burn
    attempt ledgers on no-op rungs). ids+counts only in logs."""
    from app.photo_closet.generation_service import generation_armed

    if not generation_armed():
        return

    stale = (
        db.query(IngestCandidate)
        .filter(
            IngestCandidate.user_id == user_id,
            IngestCandidate.sync_id == sync_id,
            IngestCandidate.status == "pending",
            IngestCandidate.source_type == source_type,
            IngestCandidate.generation_status == "generating",
        )
        .all()
    )
    if stale:
        for c in stale:
            c.generation_status = "pending_retry"
        db.commit()
        logger.info(
            "status-poll strand-kill user=%s sync=%s: %d stale 'generating' -> pending_retry",
            user_id, sync_id, len(stale),
        )

    import time as _time

    key = str(user_id)
    now = _time.monotonic()
    # None-sentinel, NOT 0.0: time.monotonic() is process-relative on some platforms
    # (macOS: ~0 at process start), so a 0.0 default would swallow every dispatch in
    # the process's first window.
    last = _heal_kick_last.get(key)
    if last is not None and now - last < _HEAL_KICK_WINDOW_S:
        return
    _heal_kick_last[key] = now
    if source_type == "manual":
        from app.photo_closet.generation_service import manual_generate_background

        background_tasks.add_task(manual_generate_background, str(user_id), sync_id)
    else:
        from app.photo_closet.generation_service import self_heal_background

        background_tasks.add_task(self_heal_background, str(user_id))
    logger.info("status-poll strand-heal dispatched user=%s sync=%s", user_id, sync_id)


@router.get("/pending-review", response_model=PendingReviewOut)
def get_pending_review(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PendingReviewOut:
    """Home banner feed: the newest completed run whose WHOLE batch is TERMINAL and that
    the user hasn't opened/dismissed. pending=False otherwise.

    READY-FIRST settle condition (final, Phase 3): a run surfaces ONLY when EVERY pending
    candidate in it has reached a TERMINAL pipeline_state — 'ready' (tag-complete with a
    verified, person-free, stored image) or 'failed' (excluded from the batch: it neither
    blocks the banner forever nor appears in the deck) — AND at least one is 'ready'. Any
    candidate still mid-pipeline (staged/canonicalized/image_pending/image_generated/
    verified_clean) withholds the banner. An all-'failed' batch surfaces NOTHING — silent,
    same as an empty inbox. ready_count counts ONLY the ready candidates — exactly what
    the deck will serve.

    RACE-FREE: 'ready' is written by mark_candidate_ready in the same transaction as (and
    only after validating) the image/person/tag fields it asserts, so a committed 'ready'
    row is always fully written; an uncommitted one is invisible to this read. Server-
    driven + show-once: state lives here (review_surfaced_at / review_dismissed_at), so
    the banner survives device switches and never re-nags after open/dismiss.
    JWT-pinned; only the caller's own runs. Read-only (opening/dismissing is POST ack)."""
    runs = (
        db.query(IngestRun)
        .filter(
            IngestRun.user_id == current_user.id,
            IngestRun.status == "completed",
            IngestRun.review_surfaced_at.is_(None),
            IngestRun.review_dismissed_at.is_(None),
        )
        .order_by(IngestRun.finished_at.desc().nullslast(), IngestRun.started_at.desc())
        .limit(10)
        .all()
    )
    for r in runs:
        # THE whole-batch settle gate (Photo-seam Phase 3: shared with the photo
        # status poll via review_service.settle_counts). ANY pending candidate still
        # mid-pipeline withholds the banner; needs-size cards (verified card held only
        # by a missing size) count as settled-but-reviewable so they can never block a
        # batch forever nor vanish. ready_count reports what the deck will serve
        # (ready + needs_size).
        counts = settle_counts(db, current_user.id, str(r.sync_id))
        if not counts.settled:
            continue
        if counts.reviewable > 0:
            return PendingReviewOut(
                pending=True, sync_id=str(r.sync_id), ready_count=int(counts.reviewable)
            )
    return PendingReviewOut(pending=False)


@router.post("/pending-review/ack", status_code=204)
def ack_pending_review(
    body: AckReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Mark a run's review banner as opened or dismissed so it never reappears (show-once).

    Both actions hide it (the GET gates on both timestamps being NULL). JWT-pinned; a
    foreign/unknown sync_id is a 404 (cross-user reject)."""
    run = (
        db.query(IngestRun)
        .filter(IngestRun.sync_id == body.sync_id, IngestRun.user_id == current_user.id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Sync run not found.")
    now = datetime.now(timezone.utc)
    if body.action == "dismissed":
        run.review_dismissed_at = now
    else:  # 'opened' (default) — tapping through also retires the banner
        run.review_surfaced_at = now
    db.commit()
    return None


@router.get("/candidates", response_model=List[CandidateOut])
def get_ingest_candidates(
    sync_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[CandidateOut]:
    """Return the authenticated user's status='pending' candidates for the swipe deck.

    User-scoped via the JWT (explicit user_id filter; RLS is defense-in-depth). Phase 4
    ordering: image-present cards first, then still-resolving (imageless) ones, each
    group most-confident first. Each candidate carries image_status so the deck can show
    a shimmer while resolution is in flight and poll this endpoint until nothing is
    pending. low_confidence_fields flags weak/null fields for inline edit.

    Optional ``sync_id`` scopes the deck to a single run: the photo flow passes the run
    from /photo/ingest/commit so its deck shows only that upload's garments (no stale
    pending candidates from a prior run). Omitted -> all pending (the Gmail deck,
    unchanged).
    """
    return list_pending_candidates(db, current_user.id, sync_id=sync_id)


class CandidateActionResponse(BaseModel):
    ok: bool


@router.post("/candidates/{candidate_id}/retry", response_model=CandidateActionResponse)
def retry_ingest_candidate(
    candidate_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateActionResponse:
    """Retry a terminal-'failed' candidate through the shared generation seam (Fix 2).

    Resets the attempt ledger to heal-eligible 'pending_retry' and dispatches the
    background self-heal, which re-runs it through flux2->nano->verify. Owner-scoped; a
    foreign/unknown/non-failed id -> 404. The user sees the entry return to a
    generating/ready state on the next poll (or fail again with the same honest entry)."""
    ok = retry_candidate(db, current_user.id, candidate_id)
    if not ok:
        raise HTTPException(status_code=404, detail="No failed candidate to retry.")
    from app.photo_closet.generation_service import self_heal_background

    background_tasks.add_task(self_heal_background, str(current_user.id))
    return CandidateActionResponse(ok=True)


@router.post("/candidates/{candidate_id}/dismiss", response_model=CandidateActionResponse)
def dismiss_ingest_candidate(
    candidate_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateActionResponse:
    """Dismiss a candidate from review (Fix 2) — status='rejected', nothing written to
    the closet, leaves the pending deck for good. Owner-scoped; unknown id -> 404."""
    ok = dismiss_candidate(db, current_user.id, candidate_id)
    if not ok:
        raise HTTPException(status_code=404, detail="No such candidate.")
    return CandidateActionResponse(ok=True)


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
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConfirmResponse:
    """Apply accept/reject/edit decisions for the authenticated user.

    Accepted candidates have their edits applied and UPSERT into clothing_items on
    UNIQUE(user_id, source_line_key) — re-confirming never duplicates. Rejected
    candidates write nothing. user_id is always the JWT subject; every candidate_id is
    validated to belong to the caller (cross-user / unknown ids -> 400).

    After the write, a background task enriches the newly-written items to the full
    Tier-1/2 schema and embeds them (Wave S0 Branch B). This is the ONE trigger for both
    ingest sources — Gmail AND photo candidates are confirmed through this route. The
    enrichment is Flash-Lite + async so it never slows the confirm response; ⚠️ it runs
    IN-PROCESS (Starlette threadpool, no external scheduler).
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

    # Schedule async enrichment + embedding for the just-written items (best-effort).
    written_ids = [w.clothing_item_id for w in result.written]
    if written_ids:
        from app.services.enrichment import enrich_items_background

        background_tasks.add_task(
            enrich_items_background, str(current_user.id), written_ids,
        )
        # Collage Phase 1 birth hook: matte each newborn item's display card to a
        # stored true-alpha cutout (local u2net, $0, off the response path — same
        # in-process BackgroundTasks shape as enrichment). Best-effort: a matting
        # failure leaves cutout_status NULL for the backfill sweep, never fails
        # the confirm.
        from app.services.item_cutout.service import matte_items_background

        background_tasks.add_task(
            matte_items_background, str(current_user.id), written_ids,
        )

    # --- Interaction telemetry (Wave S0 Branch C) ---------------------------
    # Server-derived: the swipe decisions that reached the closet. Accept -> `save`
    # (item_id = the written clothing_item), reject -> `dismiss` (candidate only),
    # plus `edit_field` per field the user changed in the review deck. Written in
    # the SAME db session, committed by _log_confirm_events. Best-effort: a telemetry
    # failure never fails the confirm (the closet write already succeeded).
    _log_confirm_events(db, current_user.id, body, result)

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
