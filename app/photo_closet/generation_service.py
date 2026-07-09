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
  3. flux2_pro.generate -> verify_generated_image. matches -> store, 'ready'.
  4. verify FAILS (matches False, incl. skipped) -> retry once with nano_banana.
  5. nano also fails / both unavailable / storage down -> 'pending_retry' (a later
     self-heal sweep re-attempts). generated_image_url stays NULL — the deck must NOT
     fall back to the raw crop as the product card. After GENERATION_MAX_ATTEMPTS failed
     generate->verify attempts the target goes terminal ('failed'), never re-selected.

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
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Sequence, Tuple
from uuid import UUID

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.gmail_closet.image_verify import VerifyBudget, verify_generated_image, verify_image
from app.platform.usage import UsageAccumulator, record_fill_usage
from app.models import ClothingItem, IngestCandidate, IngestRun
from app.photo_closet.dedup import dedup_check
from app.services.image_generation.base import (
    GenerationBudget,
    GenerationRequest,
    get_generation_provider,
    list_available_providers,
)

logger = logging.getLogger(__name__)

# Provider ladder for the live photo flow: FLUX.2 [pro] first (BFL, OFF the Gemini cap),
# nano_banana (Gemini, ON-cap $0.134) only as the verify-fail retry.
# get_generation_provider(name) dispatches by explicit name, so it bypasses
# GENERATION_ENABLED (that gate only guards the no-name default path).
_GENERATION_LADDER: Tuple[str, ...] = ("flux2_pro", "nano_banana")

# Generation targets: NULL (never attempted) + residue a later sweep should retry.
# 'ready' and terminal 'failed' are excluded so re-running is idempotent; a stale
# 'generating' (a crashed prior run) is re-attempted.
_RETRYABLE_STATUSES = ("pending_retry", "generating")

_SUFFIX_BY_CT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def _next_failure_status(attempts: int) -> str:
    """Terminal 'failed' once a target has burned its attempt ceiling, else 'pending_retry'.

    Cost cut #2: a permanently-failing item (verify never passes) would otherwise sit at
    'pending_retry' forever and be re-generated + re-verified by every self-heal sweep.
    After GENERATION_MAX_ATTEMPTS failed generate->verify attempts it goes terminal
    ('failed'), which every target query already excludes — so it stops being re-billed.
    Genuinely-transient misses (download error / budget / provider unavailable) do NOT
    bump the counter, so real transients keep retrying."""
    return "failed" if attempts >= settings.GENERATION_MAX_ATTEMPTS else "pending_retry"


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
        user_id = UUID(user_id_str)
        sync_id = UUID(sync_id_str)
        # Cost cut #3: ONE shared generation-call budget for the whole background
        # invocation — the main pass AND the self-heal tail draw from it, so the run can
        # never make more than GENERATION_MAX_PER_RUN generation calls total (previously
        # each allocated a fresh 50).
        gen_budget = GenerationBudget(settings.GENERATION_MAX_PER_RUN)
        run_photo_generation(user_id, db, sync_id, gen_budget=gen_budget)
        # Opportunistic self-heal (mirrors run_image_fill running at the tail of a Gmail
        # sync): now that a provider + storage are demonstrably reachable, re-attempt this
        # user's OTHER stale 'pending_retry' targets — candidates from earlier runs and
        # confirmed items that fell back to the crop. exclude_sync_id skips THIS run's
        # fresh failures (just attempted). Best-effort; never affects the commit response.
        run_generation_self_heal(user_id, db, exclude_sync_id=sync_id, gen_budget=gen_budget)
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
            # Cost cut #2: never re-select a target that has burned its attempt ceiling
            # (belt-and-suspenders with the terminal 'failed' status below).
            IngestCandidate.generation_attempts < settings.GENERATION_MAX_ATTEMPTS,
            or_(
                IngestCandidate.generation_status.is_(None),
                IngestCandidate.generation_status.in_(_RETRYABLE_STATUSES),
            ),
        )
        .order_by(IngestCandidate.created_at.asc())
        .all()
    )


@dataclass
class _CandidateOutcome:
    """What one worker did with its candidate — aggregated into GenerationStats."""
    outcome: str            # ready | held | download_error | budget | skipped
    cost_usd: float = 0.0


def run_photo_generation(
    user_id: UUID,
    db: Session,
    sync_id: UUID,
    *,
    storage_client=None,
    provider_ladder: Optional[Sequence[str]] = None,
    max_concurrency: Optional[int] = None,
    gen_budget: Optional[GenerationBudget] = None,
) -> GenerationStats:
    """Generate + verify + store a product card for each staged photo candidate.

    Candidates are generated CONCURRENTLY in a bounded thread pool (each worker owns its
    own DB session), so a multi-item photo finishes in ~the slowest single item, not the
    sum. Each worker still streams its own state (generating -> ready/pending_retry) via
    per-candidate commits, and bumps the run counters with ATOMIC SQL increments so
    concurrent updates never race. Shared Generation/Verify budgets cap total calls
    across the whole set. Finalizes the run to 'completed' once all workers finish
    (commit deliberately left it 'running'). Best-effort throughout."""
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
        # Capture ids only: each worker re-loads its candidate in its OWN session (the
        # passed-in Session is not shared across threads).
        target_ids = [c.id for c in targets]
        # Publish the denominator up front so the add-photo pill can show "0 / N".
        if run is not None:
            run.generation_total = len(targets)
            run.generation_ready = 0
            run.generation_failed = 0
            db.commit()

        if storage_client is None:
            storage_client = _storage_from_env()

        # Budgets + usage are thread-safe (lock-guarded) and SHARED across all workers,
        # so the caps apply to the whole concurrent set, not per worker. A caller may pass
        # a SHARED gen_budget (cost cut #3) so this pass and the self-heal tail draw from
        # ONE bounded pool of generation calls instead of each allocating a fresh 50.
        if gen_budget is None:
            gen_budget = GenerationBudget(settings.GENERATION_MAX_PER_RUN)
        verify_budget = VerifyBudget(settings.GMAIL_VERIFY_MAX_PER_RUN)
        usage = UsageAccumulator()

        if target_ids:
            cap = max(1, int(max_concurrency or settings.GENERATION_MAX_CONCURRENCY))
            workers = min(cap, len(target_ids))
            with ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="photogen"
            ) as pool:
                futures = [
                    pool.submit(
                        _generate_candidate, cid, user_id, sync_id, storage_client,
                        ladder, gen_budget, verify_budget, usage,
                    )
                    for cid in target_ids
                ]
                for fut in futures:
                    r = fut.result()  # workers catch their own errors — never raise
                    if r.outcome == "ready":
                        stats.ready += 1
                        stats.cost_usd += r.cost_usd
                    elif r.outcome == "download_error":
                        stats.held += 1
                        stats.download_errors += 1
                    elif r.outcome == "held":
                        stats.held += 1
                    elif r.outcome == "budget":
                        stats.budget_stopped = True
                    # "skipped" (dedup / vanished row) -> no counter, no stat

        # Pull the workers' committed counter increments into the passed-in session so
        # record_fill_usage / _finalize_run and any caller reading `run` see final values.
        if run is not None:
            db.refresh(run)

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


def _generate_candidate(
    candidate_id,
    user_id: UUID,
    sync_id: UUID,
    storage_client,
    ladder: Tuple[str, ...],
    gen_budget: GenerationBudget,
    verify_budget: VerifyBudget,
    usage: UsageAccumulator,
) -> _CandidateOutcome:
    """Run the ladder for ONE candidate in its OWN DB session (a pool worker).

    Streams state via per-candidate commits and bumps the run counters atomically. Never
    raises — any failure holds the candidate for a later retry sweep."""
    from app.db import SessionLocal  # late import: worker-owned, thread-safe session

    db = SessionLocal()
    try:
        cand = (
            db.query(IngestCandidate)
            .filter(
                IngestCandidate.id == candidate_id,
                IngestCandidate.user_id == user_id,
            )
            .first()
        )
        if cand is None:
            return _CandidateOutcome("skipped")

        # Gate on the dedup seam: only unique survivors generate (stub: always unique —
        # wires the seam so the real matcher drops in with no change).
        if dedup_check(db, user_id, cand).verdict != "unique":
            return _CandidateOutcome("skipped")

        # Fast-path skip when the SHARED budget is already spent (cost cut #3): don't
        # churn a 'generating' write + cutout download we can't act on. The authoritative
        # per-CALL take() lives in the ladder loop below.
        if gen_budget.remaining <= 0:
            return _CandidateOutcome("budget")

        # Mark 'generating' and stream it immediately (the deck renders the loading state).
        cand.generation_status = "generating"
        db.commit()

        dl = _download_bytes(cand.image_url)
        if dl is None:
            _hold(db, cand, sync_id, count_attempt=False)  # transient -> no ceiling bump
            return _CandidateOutcome("download_error")
        ref_bytes, ref_ct = dl

        calls_made = 0
        for provider_name in ladder:
            # BUDGET COUNTS CALLS (cost cut #3): consume one unit per ACTUAL generation
            # call, so a 2-rung ladder costs 2 units and MAX_PER_RUN is a real ceiling.
            if not gen_budget.take():
                break  # shared budget exhausted mid-ladder
            calls_made += 1
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

            # Candidate write + atomic counter increment in ONE transaction. The
            # `generation_ready = generation_ready + 1` runs as a single SQL UPDATE, so
            # concurrent workers can't lose an increment (row-level lock serializes them).
            cand.generated_image_url = url
            cand.generation_status = "ready"
            db.query(IngestRun).filter(IngestRun.sync_id == sync_id).update(
                {IngestRun.generation_ready: IngestRun.generation_ready + 1},
                synchronize_session=False,
            )
            db.commit()
            return _CandidateOutcome("ready", float(result.cost_usd or 0.0))

        if calls_made == 0:
            # Budget ran out before any generation call (race with concurrent workers):
            # revert to clean NULL residue for a later run, report 'budget'. NOT counted
            # as a failed attempt (nothing was generated/verified).
            cand.generation_status = None
            db.commit()
            return _CandidateOutcome("budget")

        # Ladder exhausted after real attempts (or storage down after a pass): hold for a
        # later sweep and bump the attempt ceiling.
        _hold(db, cand, sync_id, count_attempt=True)
        return _CandidateOutcome("held")
    except Exception as exc:
        logger.warning(
            "generation candidate sync=%s: %s", sync_id, type(exc).__name__
        )
        try:
            db.rollback()
        except Exception:
            pass
        return _CandidateOutcome("held")
    finally:
        db.close()


def _hold(
    db: Session, cand: IngestCandidate, sync_id: UUID, *, count_attempt: bool = True
) -> None:
    """Hold a candidate for a later sweep + atomically bump the run's generation_failed.

    generated_image_url is left NULL and image_url (the crop) untouched — the deck must
    not show the raw cutout as the finished product card.

    ``count_attempt`` (cost cut #2): a real generate->verify miss bumps the per-item
    generation_attempts counter and goes terminal ('failed') once the ceiling is burned;
    a transient miss (download error) passes count_attempt=False so it keeps retrying and
    never poisons the ceiling."""
    if count_attempt:
        cand.generation_attempts = (cand.generation_attempts or 0) + 1
        cand.generation_status = _next_failure_status(cand.generation_attempts)
    else:
        cand.generation_status = "pending_retry"
    db.query(IngestRun).filter(IngestRun.sync_id == sync_id).update(
        {IngestRun.generation_failed: IngestRun.generation_failed + 1},
        synchronize_session=False,
    )
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


# ---------------------------------------------------------------------------
# Self-heal sweep — re-attempt 'pending_retry' generation targets (Wave 2)
# ---------------------------------------------------------------------------
#
# A per-sync generation pass (run_photo_generation) attempts each staged candidate ONCE;
# targets where both providers fail verify are left 'pending_retry' and the run finalizes
# — without this sweep they'd dead-end forever. This is the generation analog of the
# Phase 4 image_fill self-heal: idempotent (only 'pending_retry' with a usable crop is a
# target; 'ready' rows are never touched), budget-capped (shared Generation/Verify
# budgets + a per-sweep row cap), and safe to run repeatedly. It re-generates FROM the
# stored crop (candidate.image_url / item.image_url), verifies with the SAME mandatory
# fidelity gate, and only then persists — no unverified image is ever stored.
#
# Covers BOTH lifecycle stages:
#   * pre-confirm  ingest_candidates -> writes generated_image_url + generation_status
#   * confirmed    clothing_items    -> the card IS image_url, so success replaces it and
#                                       flips generation_status (the crop is the source it
#                                       regenerated from; on failure image_url stays the crop)
#
# SECURITY/PRIVACY: user_id is server-pinned (the caller's, never a body); every query is
# filtered by user_id (per-user isolation / RLS-aligned); SSRF + verify gates are the same
# ones the live path uses; only ids/counts/statuses are logged, never image bytes/PII.

_SELF_HEAL_STATUS = "pending_retry"


@dataclass
class SelfHealStats:
    """Redaction-safe summary of one self-heal sweep (no image bytes / PII)."""
    user_id: UUID
    candidates_seen: int = 0
    items_seen: int = 0
    ready: int = 0             # verified + stored -> flipped to 'ready'
    held: int = 0             # still could not verify/store -> left 'pending_retry'
    download_errors: int = 0  # stored crop could not be re-fetched (left 'pending_retry')
    budget_stopped: bool = False
    cost_usd: float = 0.0


@dataclass
class _HealOutcome:
    outcome: str                 # ready | held | download_error | budget
    url: Optional[str] = None    # stored generated-card URL on success
    cost_usd: float = 0.0


def _generate_from_crop(
    *,
    crop_url: str,
    name: Optional[str],
    category: Optional[str],
    color: Optional[str],
    brand: Optional[str],
    storage_client,
    user_id: UUID,
    ladder: Tuple[str, ...],
    gen_budget: GenerationBudget,
    verify_budget: VerifyBudget,
    usage: UsageAccumulator,
    steering: Optional[str] = None,
) -> _HealOutcome:
    """Run the provider ladder on a stored crop, gated by the mandatory verify.

    Returns a stored URL only when a provider's output PASSES verify against the crop —
    a skipped/disabled verify is never a pass. Makes NO DB writes (the caller persists),
    so it's reusable for both candidates and confirmed items.

    ``steering`` is an OPTIONAL untrusted user correction (Regenerate reason). It is
    fenced inside the prompt (prompt._steering_clause) and NEVER relaxes the verify gate —
    a steered generation still has to pass verify against the crop, so a reason cannot
    force a hallucinated result through.

    BUDGET COUNTS CALLS (cost cut #3): gen_budget.take() is consumed once per ACTUAL
    provider call (in the rung loop), and the SHARED budget passed in by the caller means
    self-heal draws from the SAME bounded pool as the main pass — never a fresh 50."""
    if gen_budget.remaining <= 0:
        return _HealOutcome("budget")
    dl = _download_bytes(crop_url)
    if dl is None:
        return _HealOutcome("download_error")
    ref_bytes, ref_ct = dl
    calls_made = 0
    for provider_name in ladder:
        if not gen_budget.take():
            break  # shared budget exhausted mid-ladder
        calls_made += 1
        provider = get_generation_provider(provider_name)
        result = provider.generate(
            GenerationRequest(
                image_bytes=ref_bytes,
                content_type=ref_ct,
                name=name,
                category=category,
                color=color,
                pattern=None,
                brand=brand,
                steering=steering,
            )
        )
        if result is None:
            continue  # provider failure / unavailable -> next rung
        verdict = verify_generated_image(
            reference_bytes=ref_bytes,
            reference_content_type=ref_ct,
            candidate_bytes=result.image_bytes,
            candidate_content_type=result.content_type,
            category=category,
            color=color,
            pattern=None,
            name=name,
            budget=verify_budget,
            usage=usage,
        )
        if not verdict.matches:  # MANDATORY gate — skipped verify is NOT a pass
            continue
        url = _store_generated(storage_client, user_id, result.image_bytes, result.content_type)
        if not url:
            break  # passed verify but storage down -> hold for a later sweep
        return _HealOutcome("ready", url=url, cost_usd=float(result.cost_usd or 0.0))
    # Budget denied before any call -> 'budget' (caller stops the sweep); a real attempt
    # that missed -> 'held' (caller bumps the item's attempt ceiling).
    return _HealOutcome("budget" if calls_made == 0 else "held")


def run_generation_self_heal(
    user_id: UUID,
    db: Session,
    *,
    exclude_sync_id: Optional[UUID] = None,
    item_limit: Optional[int] = None,
    storage_client=None,
    provider_ladder: Optional[Sequence[str]] = None,
    gen_budget: Optional[GenerationBudget] = None,
) -> SelfHealStats:
    """Re-attempt generation for a user's 'pending_retry' targets. Never raises.

    Targets (each filtered by user_id — per-user isolation):
      * pre-confirm ingest_candidates: photo, status='pending', generation_status=
        'pending_retry', crop present (image_url), no card yet (generated_image_url NULL).
        ``exclude_sync_id`` skips a run whose candidates were JUST attempted (the commit
        that triggered this sweep), so we don't immediately re-hit its fresh failures.
      * confirmed clothing_items: photo, generation_status='pending_retry', crop present.

    Both target sets exclude rows that have burned GENERATION_MAX_ATTEMPTS (cost cut #2):
    a permanently-failing item goes terminal ('failed') after N misses and is never
    re-selected, so a self-heal sweep stops re-billing gen + 2×verify for it every run.

    ``gen_budget`` (cost cut #3): the caller (generate_background / the worker) passes the
    SAME budget it gave run_photo_generation, so the main pass + this self-heal tail share
    ONE bounded pool of generation calls instead of each allocating a fresh
    GENERATION_MAX_PER_RUN. Default None -> a fresh budget (standalone / dev-script use).

    Idempotent + budget-capped; safe to run repeatedly. A no-op when generation isn't
    armed (no provider -> every rung returns None -> targets stay 'pending_retry')."""
    stats = SelfHealStats(user_id=user_id)
    try:
        ladder = tuple(provider_ladder or _GENERATION_LADDER)
        limit = item_limit or settings.GENERATION_SELF_HEAL_MAX_ITEMS

        cand_q = db.query(IngestCandidate).filter(
            IngestCandidate.user_id == user_id,
            IngestCandidate.source_type == "photo",
            IngestCandidate.status == "pending",
            IngestCandidate.generation_status == _SELF_HEAL_STATUS,
            IngestCandidate.image_url.isnot(None),
            IngestCandidate.generated_image_url.is_(None),
            IngestCandidate.generation_attempts < settings.GENERATION_MAX_ATTEMPTS,
        )
        if exclude_sync_id is not None:
            cand_q = cand_q.filter(IngestCandidate.sync_id != exclude_sync_id)
        cand_rows = cand_q.order_by(IngestCandidate.created_at.asc()).limit(limit).all()

        item_rows: List[ClothingItem] = []
        remaining = max(0, limit - len(cand_rows))
        if remaining:
            item_rows = (
                db.query(ClothingItem)
                .filter(
                    ClothingItem.user_id == user_id,
                    ClothingItem.source_type == "photo",
                    ClothingItem.generation_status == _SELF_HEAL_STATUS,
                    ClothingItem.image_url.isnot(None),
                    ClothingItem.generation_attempts < settings.GENERATION_MAX_ATTEMPTS,
                )
                .order_by(ClothingItem.created_at.desc())
                .limit(remaining)
                .all()
            )

        stats.candidates_seen = len(cand_rows)
        stats.items_seen = len(item_rows)
        if not cand_rows and not item_rows:
            return stats

        if storage_client is None:
            storage_client = _storage_from_env()

        # Cost cut #3: share the caller's bounded budget when supplied (main pass + this
        # tail draw from ONE pool); otherwise a fresh cap for standalone/dev-script runs.
        if gen_budget is None:
            gen_budget = GenerationBudget(settings.GENERATION_MAX_PER_RUN)
        verify_budget = VerifyBudget(settings.GMAIL_VERIFY_MAX_PER_RUN)
        usage = UsageAccumulator()

        def _heal(crop_url, name, category, color, brand):
            return _generate_from_crop(
                crop_url=crop_url, name=name, category=category, color=color, brand=brand,
                storage_client=storage_client, user_id=user_id, ladder=ladder,
                gen_budget=gen_budget, verify_budget=verify_budget, usage=usage,
            )

        # --- pre-confirm candidates: write the card to generated_image_url ---------
        for c in cand_rows:
            r = _heal(c.image_url, c.name, c.category, c.color, c.brand)
            if r.outcome == "budget":
                stats.budget_stopped = True
                break
            if r.outcome == "download_error":
                stats.download_errors += 1
                stats.held += 1
                continue
            if r.url:
                c.generated_image_url = r.url
                c.generation_status = "ready"
                c.generation_attempts = 0  # verified success clears the failure ledger
                db.commit()
                stats.ready += 1
                stats.cost_usd += r.cost_usd
            else:
                # Real generate->verify miss: bump the attempt ceiling; terminal at N.
                c.generation_attempts = (c.generation_attempts or 0) + 1
                c.generation_status = _next_failure_status(c.generation_attempts)
                db.commit()
                stats.held += 1

        # --- confirmed items: the card IS image_url, so success replaces it --------
        if not stats.budget_stopped:
            for it in item_rows:
                r = _heal(it.image_url, it.name, it.category, it.color_primary, it.brand)
                if r.outcome == "budget":
                    stats.budget_stopped = True
                    break
                if r.outcome == "download_error":
                    stats.download_errors += 1
                    stats.held += 1
                    continue
                if r.url:
                    it.image_url = r.url
                    it.generation_status = "ready"
                    it.generation_attempts = 0  # verified success clears the ledger
                    db.commit()
                    stats.ready += 1
                    stats.cost_usd += r.cost_usd
                else:
                    # Real generate->verify miss: bump the attempt ceiling; terminal at N.
                    it.generation_attempts = (it.generation_attempts or 0) + 1
                    it.generation_status = _next_failure_status(it.generation_attempts)
                    db.commit()
                    stats.held += 1

        logger.info(
            "generation self-heal user=%s: candidates=%d items=%d -> ready=%d held=%d "
            "dl_err=%d budget_stopped=%s cost_usd=%.4f",
            user_id, stats.candidates_seen, stats.items_seen, stats.ready, stats.held,
            stats.download_errors, stats.budget_stopped, stats.cost_usd,
        )
        return stats
    except Exception as exc:  # background tail must never crash the caller
        logger.error("generation self-heal user=%s: %s: %s", user_id, type(exc).__name__, exc)
        try:
            db.rollback()
        except Exception:
            pass
        return stats


# ---------------------------------------------------------------------------
# Single-item Regenerate (item detail page) — reuses the ladder + verify gate
# ---------------------------------------------------------------------------
#
# The user can ask to REGENERATE one confirmed photo item's product card, optionally
# with a free-text "what was wrong?" reason that STEERS the generation (fenced as
# untrusted garment description — prompt._steering_clause). This reuses _generate_from_crop
# verbatim: same provider ladder, same MANDATORY verify gate. The current image is the
# source + verify reference and is NEVER blanked — it stays until a NEW image passes
# verify, so a verify-fail simply keeps the existing card (the UI shows a gentle
# "couldn't improve it" rather than a blank). SCRUM-44 quota is recorded at the route, not
# here (this core is reused by the worker + BackgroundTasks paths).


@dataclass
class RegenOutcome:
    """Result of one Regenerate. ``changed`` = a new verified image replaced the old."""
    status: str            # ready | held | skipped
    changed: bool = False
    cost_usd: float = 0.0


def run_item_regeneration(
    user_id: UUID,
    db: Session,
    item_id: UUID,
    *,
    reason: Optional[str] = None,
    reference_url: Optional[str] = None,
    storage_client=None,
    provider_ladder: Optional[Sequence[str]] = None,
) -> RegenOutcome:
    """Regenerate ONE clothing_item's product image. Never raises.

    Wave B (Fix 4): ANY owned item is eligible — Gmail items and image-less items too, not
    just photo-items-with-an-image. Source preference, highest first:
      1. ``reference_url`` — an uploaded reference image (already validated + stored by the
         route) → reference-conditioned generation (verify_generated_image, person backstop).
      2. the item's current ``image_url`` → same reference-conditioned path.
      3. neither (image-less item, no upload) → text-to-image from the item's attributes
         (verify_image + mandatory no-person).
    Optionally steered by the untrusted ``reason`` (fenced in the prompt; never relaxes
    verify). On a verified pass image_url is set and generation_status -> 'ready'; on ANY
    miss the existing image is KEPT (never blanked) and the item is left 'pending_retry'.
    user_id-scoped: a foreign/unknown item_id is a no-op 'skipped'."""
    item = None
    try:
        item = (
            db.query(ClothingItem)
            .filter(ClothingItem.id == item_id, ClothingItem.user_id == user_id)
            .first()
        )
        if item is None:
            return RegenOutcome("skipped")

        ladder = tuple(provider_ladder or _GENERATION_LADDER)
        if storage_client is None:
            storage_client = _storage_from_env()
        gen_budget = GenerationBudget(settings.GENERATION_MAX_PER_RUN)
        verify_budget = VerifyBudget(settings.GMAIL_VERIFY_MAX_PER_RUN)
        usage = UsageAccumulator()

        ref_url = reference_url or item.image_url
        if ref_url:
            r = _generate_from_crop(
                crop_url=ref_url,
                name=item.name,
                category=item.category,
                color=item.color_primary,
                brand=item.brand,
                storage_client=storage_client,
                user_id=user_id,
                ladder=ladder,
                gen_budget=gen_budget,
                verify_budget=verify_budget,
                usage=usage,
                steering=reason,
            )
            new_url, cost, miss = r.url, r.cost_usd, r.outcome
        else:
            # No reference at all -> text-to-image from attributes (verified + person-free).
            from app.services.image_generation.generate_core import generate_from_text

            g = generate_from_text(
                name=item.name,
                category=item.category,
                color=item.color_primary,
                brand=item.brand,
                storage_client=storage_client,
                user_id=user_id,
                gen_budget=gen_budget,
                verify_budget=verify_budget,
                usage=usage,
                steering=reason,
            )
            new_url, cost, miss = g.url, g.cost_usd, g.outcome

        if new_url:
            item.image_url = new_url
            item.generation_status = "ready"
            item.generation_attempts = 0  # verified success clears the failure ledger
            db.commit()
            logger.info(
                "item regen user=%s item=%s: ready (steered=%s ref=%s)",
                user_id, item_id, bool(reason), bool(reference_url),
            )
            return RegenOutcome("ready", changed=True, cost_usd=cost)

        # Miss: keep the current image (may be None for an image-less item). A real
        # generate->verify miss ('held') bumps the attempt ceiling and goes terminal at N
        # (cost cut #2 — stops self-heal re-billing it); a transient miss (budget /
        # download error) just leaves it 'pending_retry' for a later sweep.
        if miss == "held":
            item.generation_attempts = (item.generation_attempts or 0) + 1
            item.generation_status = _next_failure_status(item.generation_attempts)
        else:
            item.generation_status = "pending_retry"
        db.commit()
        logger.info("item regen user=%s item=%s: held (%s)", user_id, item_id, miss)
        return RegenOutcome("held")
    except Exception as exc:
        logger.error("run_item_regeneration item=%s: %s", item_id, type(exc).__name__)
        try:
            db.rollback()
            # Don't strand the card stuck 'generating' after a crash.
            stuck = (
                db.query(ClothingItem)
                .filter(ClothingItem.id == item_id, ClothingItem.user_id == user_id)
                .first()
            )
            if stuck is not None and stuck.generation_status == "generating":
                stuck.generation_status = "pending_retry"
                db.commit()
        except Exception:
            pass
        return RegenOutcome("held")


def regenerate_item_background(
    user_id_str: str,
    item_id_str: str,
    reason: Optional[str] = None,
    reference_url: Optional[str] = None,
) -> None:
    """BackgroundTasks entry point (mirrors generate_background): own DB session, never
    raises. Used when the durable-jobs flag is OFF; the worker path calls
    run_item_regeneration directly. ``reference_url`` is an optional uploaded reference
    image (validated + stored by the route) to condition the regeneration on."""
    from app.db import SessionLocal  # late import avoids a module-level import cycle

    db = SessionLocal()
    try:
        run_item_regeneration(
            UUID(user_id_str), db, UUID(item_id_str),
            reason=reason, reference_url=reference_url,
        )
    except Exception as exc:
        logger.error(
            "regenerate_item_background: %s: %s", type(exc).__name__, exc
        )
    finally:
        db.close()
