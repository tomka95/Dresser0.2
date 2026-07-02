"""Wave 2 background product-image generation for photo candidates.

WHERE THIS SITS
---------------
POST /photo/ingest/commit stages each selected garment as an ingest_candidate with
image_url = the raw CUTOUT and image_status = 'user_uploaded'. This module runs AFTER
commit, in a background thread (mirrors gmail_closet.fetch_service.ingest_background):
for every freshly staged photo candidate it turns the cutout into a clean product-card
image, verifies it against the cutout, and stores the VERIFIED result on a SEPARATE
field (generated_image_url) so the raw crop (image_url) is never overwritten.

THE PER-CANDIDATE LADDER
------------------------
  1. Fetch the cutout bytes back from candidate.image_url (feeds BOTH the generation
     request AND the verify reference).
  2. generation_status = 'generating' (streamed: the deck can show a progress state).
  3. nano_banana.generate -> verify_generated_image. matches -> store, 'ready'.
  4. verify FAILS (matches False, incl. skipped) -> retry once with flux_kontext.
  5. flux also fails / both unavailable / storage down -> 'pending_retry' (a later
     self-heal sweep re-attempts). generated_image_url stays NULL — the deck must NOT
     fall back to the raw crop as the product card.

SAFETY / COST
-------------
The fidelity gate is MANDATORY: an image is stored ONLY when verify returns
matches=True — a skipped/disabled verify never stores (nano's logo-hallucination risk
is the reason the gate exists). Idempotent: 'ready' candidates are excluded from the
target query, so re-running never regenerates a finished card. Budget-capped
(GENERATION_MAX_PER_RUN generations, GMAIL_VERIFY_MAX_PER_RUN verifies per run).
user_id is server-pinned (the caller's JWT subject, threaded from the route). Never
logs image bytes / PII — ids, counts, hashes, statuses only.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple
from uuid import UUID

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.gmail_closet.image_verify import VerifyBudget, verify_generated_image
from app.gmail_closet.usage import UsageAccumulator, record_fill_usage
from app.models import IngestCandidate, IngestRun
from app.photo_closet.dedup import dedup_check
from app.services.image_generation.base import (
    GenerationBudget,
    GenerationRequest,
    get_generation_provider,
    list_available_providers,
)

logger = logging.getLogger(__name__)

# Provider ladder for the live photo flow: nano_banana first, flux_kontext on a
# verify-fail retry. get_generation_provider(name) dispatches by explicit name, so it
# bypasses GENERATION_ENABLED (that gate only guards the no-name default path).
_GENERATION_LADDER: Tuple[str, ...] = ("nano_banana", "flux_kontext")

# Generation targets: NULL (never attempted) + residue a later sweep should retry.
# 'ready' and terminal 'failed' are excluded so re-running is idempotent; a stale
# 'generating' (a crashed prior run) is re-attempted.
_RETRYABLE_STATUSES = ("pending_retry", "generating")

_SUFFIX_BY_CT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


@dataclass
class GenerationStats:
    """Redaction-safe summary of one generation pass (no image bytes / PII)."""
    user_id: UUID
    sync_id: UUID
    targets: int = 0
    ready: int = 0            # verified + stored
    held: int = 0            # left 'pending_retry' (verify/provider/storage miss)
    download_errors: int = 0  # cutout could not be re-fetched
    budget_stopped: bool = False
    cost_usd: float = 0.0     # observed generation spend (per-image rates)


# ---------------------------------------------------------------------------
# Injectable seams (module-level so tests monkeypatch without network / bucket)
# ---------------------------------------------------------------------------

def _download_bytes(url: str) -> Optional[Tuple[bytes, str]]:
    """GET the stored cutout back as (bytes, content_type). None on any miss.

    The cutout lives at a Supabase public URL written at commit; we re-fetch it so the
    background job is fully decoupled from the request (which never held the bytes)."""
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as http:
            resp = http.get(url)
    except Exception as exc:
        logger.warning("generation: cutout download error (%s)", type(exc).__name__)
        return None
    if resp.status_code != 200 or not resp.content:
        logger.warning("generation: cutout download HTTP %s / empty", resp.status_code)
        return None
    ct = (resp.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
    return resp.content, ct


def _storage_from_env():
    """Build the Supabase storage client, or None if the bucket isn't configured."""
    try:
        from app.utils.supabase_storage import SupabaseStorageClient

        return SupabaseStorageClient.from_env()
    except Exception as exc:  # missing S3 env / client init failure
        logger.warning("generation: storage unavailable (%s)", type(exc).__name__)
        return None


def _store_generated(
    storage_client, user_id: UUID, data: bytes, content_type: str
) -> Optional[str]:
    """Persist verified generated bytes via the content-addressed image_blobs dedup.

    Mirrors ingest_service.store_cutout (same dedup path), into a separate folder.
    Returns the stored URL, or None if storage is unavailable."""
    if storage_client is None:
        return None
    from app.utils.image_blob_store import get_or_upload

    suffix = _SUFFIX_BY_CT.get(content_type, ".png")
    return get_or_upload(
        data,
        lambda: storage_client.upload_bytes(
            data,
            folder=f"generated_items/{user_id}",
            content_type=content_type,
            suffix=suffix,
        ),
    )


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def generation_armed() -> bool:
    """True when generation CAN run: a ladder provider key + a verify key present.

    Verify uses GEMINI_API_KEY; nano_banana's own key IS GEMINI_API_KEY. So this is
    'at least one ladder provider configured AND verify configured' — the route uses it
    to decide whether to defer run-completion + dispatch the job (vs. finalize at commit
    and leave cards as raw cutouts when generation isn't set up)."""
    available = list_available_providers()
    has_provider = any(available.get(name) for name in _GENERATION_LADDER)
    return has_provider and bool(settings.GEMINI_API_KEY)


def generate_background(user_id_str: str, sync_id_str: str) -> None:
    """Background-task entry point (Starlette runs sync tasks in a thread pool).

    Creates its OWN DB session, fully decoupled from the request session (already
    closed before this runs), then generates for the run's staged photo candidates.
    Never raises — a failure here can only leave residue as 'pending_retry'."""
    from app.db import SessionLocal  # late import avoids a module-level import cycle

    db = SessionLocal()
    try:
        run_photo_generation(UUID(user_id_str), db, UUID(sync_id_str))
    except Exception as exc:
        logger.error(
            "generate_background: unhandled error — %s: %s", type(exc).__name__, exc
        )
    finally:
        db.close()


def _select_targets(db: Session, user_id: UUID, sync_id: UUID) -> List[IngestCandidate]:
    """This run's pending photo candidates that still need a generated card.

    Requires image_url (the cutout to generate FROM). Excludes 'ready'/'failed' so
    re-running is idempotent."""
    return (
        db.query(IngestCandidate)
        .filter(
            IngestCandidate.user_id == user_id,
            IngestCandidate.sync_id == sync_id,
            IngestCandidate.source_type == "photo",
            IngestCandidate.status == "pending",
            IngestCandidate.image_url.isnot(None),
            or_(
                IngestCandidate.generation_status.is_(None),
                IngestCandidate.generation_status.in_(_RETRYABLE_STATUSES),
            ),
        )
        .order_by(IngestCandidate.created_at.asc())
        .all()
    )


def run_photo_generation(
    user_id: UUID,
    db: Session,
    sync_id: UUID,
    *,
    storage_client=None,
    provider_ladder: Optional[Sequence[str]] = None,
) -> GenerationStats:
    """Generate + verify + store a product card for each staged photo candidate.

    Finalizes the run to 'completed' when the pass ends (commit deliberately left it
    'running' so /status reports generation-in-flight). Best-effort throughout."""
    ladder = tuple(provider_ladder or _GENERATION_LADDER)
    stats = GenerationStats(user_id=user_id, sync_id=sync_id)
    run = (
        db.query(IngestRun)
        .filter(IngestRun.sync_id == sync_id, IngestRun.user_id == user_id)
        .first()
    )
    try:
        targets = _select_targets(db, user_id, sync_id)
        stats.targets = len(targets)
        # Publish the denominator up front so the add-photo pill can show "0 / N".
        if run is not None:
            run.generation_total = len(targets)
            run.generation_ready = 0
            run.generation_failed = 0
            db.commit()

        if storage_client is None:
            storage_client = _storage_from_env()

        gen_budget = GenerationBudget(settings.GENERATION_MAX_PER_RUN)
        verify_budget = VerifyBudget(settings.GMAIL_VERIFY_MAX_PER_RUN)
        usage = UsageAccumulator()

        for cand in targets:
            # Gate on the dedup seam: only unique survivors generate (stub: always
            # unique — wires the seam so the real matcher drops in with no change).
            if dedup_check(db, user_id, cand).verdict != "unique":
                continue
            if not gen_budget.take():
                stats.budget_stopped = True
                logger.info("generation sync=%s: budget cap hit, residue left", sync_id)
                break
            _generate_one(
                db, cand, run, storage_client, ladder, verify_budget, usage, stats
            )

        # Roll the pair-pass verify cost onto the run (per-model priced).
        record_fill_usage(db, sync_id, usage)
    except Exception as exc:
        logger.error("run_photo_generation sync=%s: %s", sync_id, type(exc).__name__)
    finally:
        _finalize_run(db, run)

    logger.info(
        "generation done sync=%s user=%s: targets=%d ready=%d held=%d dl_err=%d "
        "budget_stopped=%s cost_usd=%.4f",
        sync_id, user_id, stats.targets, stats.ready, stats.held,
        stats.download_errors, stats.budget_stopped, stats.cost_usd,
    )
    return stats


def _generate_one(
    db: Session,
    cand: IngestCandidate,
    run: Optional[IngestRun],
    storage_client,
    ladder: Tuple[str, ...],
    verify_budget: VerifyBudget,
    usage: UsageAccumulator,
    stats: GenerationStats,
) -> None:
    """Run the ladder for ONE candidate; commit its terminal state (stream per item)."""
    # Mark 'generating' and stream it (the deck can render a progress state).
    cand.generation_status = "generating"
    db.commit()

    dl = _download_bytes(cand.image_url)
    if dl is None:
        stats.download_errors += 1
        _hold_for_retry(db, cand, run, stats)
        return
    ref_bytes, ref_ct = dl

    for provider_name in ladder:
        provider = get_generation_provider(provider_name)
        result = provider.generate(
            GenerationRequest(
                image_bytes=ref_bytes,
                content_type=ref_ct,
                name=cand.name,
                category=cand.category,
                color=cand.color,
                pattern=None,  # no pattern column on ingest_candidates
                brand=cand.brand,
            )
        )
        if result is None:
            continue  # provider failure / unavailable -> next rung

        verdict = verify_generated_image(
            reference_bytes=ref_bytes,
            reference_content_type=ref_ct,
            candidate_bytes=result.image_bytes,
            candidate_content_type=result.content_type,
            category=cand.category,
            color=cand.color,
            pattern=None,
            name=cand.name,
            budget=verify_budget,
            usage=usage,
        )
        # MANDATORY gate: a skipped/disabled verify is NOT a pass — never store it.
        if not verdict.matches:
            continue

        url = _store_generated(
            storage_client, cand.user_id, result.image_bytes, result.content_type
        )
        if not url:
            # Passed verify but storage is down — can't persist a card; hold + retry.
            break

        cand.generated_image_url = url
        cand.generation_status = "ready"
        stats.ready += 1
        stats.cost_usd += float(result.cost_usd or 0.0)
        if run is not None:
            run.generation_ready = (run.generation_ready or 0) + 1
        db.commit()
        return

    # Ladder exhausted (or storage down after a pass): hold for a later sweep.
    _hold_for_retry(db, cand, run, stats)


def _hold_for_retry(
    db: Session, cand: IngestCandidate, run: Optional[IngestRun], stats: GenerationStats
) -> None:
    """No verified card this pass: mark 'pending_retry', leave generated_image_url NULL.

    image_url (the crop) is deliberately untouched — the deck must not show the raw
    cutout as the finished product card."""
    cand.generation_status = "pending_retry"
    stats.held += 1
    if run is not None:
        run.generation_failed = (run.generation_failed or 0) + 1
    db.commit()


def _finalize_run(db: Session, run: Optional[IngestRun]) -> None:
    """Flip the deferred run to 'completed' once generation ends (best-effort)."""
    if run is None:
        return
    try:
        if run.status == "running":
            from app.photo_closet.ingest_service import _utc_now

            run.status = "completed"
            run.finished_at = _utc_now()
            db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
