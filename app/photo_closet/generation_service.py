"""Wave 2 background product-image generation for photo candidates.

WHERE THIS SITS
---------------
POST /photo/ingest/commit stages each selected garment as an ingest_candidate with
image_url = the raw CUTOUT and image_status = 'user_uploaded'. This module runs AFTER
commit, in a background thread (mirrors gmail_closet.fetch_service.ingest_background):
for every freshly staged photo candidate it turns the cutout into a clean product-card
image, verifies it against the cutout, and stores the VERIFIED result on a SEPARATE
field (generated_image_url) so the raw crop (image_url) is never overwritten.

THE PER-CANDIDATE FLOW (Photo-seam Phase 1: ONE shared seam)
------------------------------------------------------------
  1. Shared product_image_cache lookup (BRANDED items only — product identity): a card
     verified once, by any user, either pipeline, serves again at zero cost.
  2. generation_status = 'generating' (streamed: the deck can show a progress state);
     fetch the cutout bytes back from candidate.image_url.
  3. generate_core.generate_from_reference_bytes — the SAME generate→verify→store seam
     the Gmail pipeline runs: FLUX.2 [pro] rung-1 (off-cap) -> nano_banana verify-fail
     retry, every candidate gated by the MANDATORY verify_generated_image (person
     backstop + garment/color/pattern/logo fidelity), stored to generated_items/.
  4. Verified card -> generated_image_url + the SHARED readiness machine
     (services.readiness.mark_candidate_ready — ready ⟺ person_free + verified card +
     complete tags); branded cards are promoted back into the shared cache.
  5. Both rungs fail / storage down -> 'pending_retry' (a later self-heal sweep
     re-attempts). generated_image_url stays NULL — the deck must NOT fall back to the
     raw crop as the product card. After GENERATION_MAX_ATTEMPTS failed generate->verify
     attempts the target goes terminal ('failed'), never re-selected.

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
from app.gmail_closet.image_verify import VerifyBudget
from app.gmail_closet.product_image_cache import lookup_verified, make_cache_key, promote_verified
from app.platform.usage import UsageAccumulator, record_fill_usage
from app.models import ClothingItem, IngestCandidate, IngestRun
from app.photo_closet.dedup import dedup_check
from app.services.closet_canonicalize import default_size_for_category, load_user_facts
from app.services.image_generation.base import GenerationBudget
from app.services.image_generation.generate_core import (
    generate_from_reference_bytes,
    generation_armed as _core_generation_armed,
)
from app.services.readiness import advance, mark_candidate_ready, tags_ready

logger = logging.getLogger(__name__)

# Photo-seam Phase 1: NO photo-local provider ladder anymore. Generation, the mandatory
# verify gate and card storage all live in the ONE shared core
# (app.services.image_generation.generate_core) — the same seam the Gmail on-model /
# t2i paths run. ``provider_ladder=None`` means the core's ladder
# (FLUX.2 [pro] rung-1 off-cap -> nano_banana verify-fail retry).

# Generation targets: NULL (never attempted) + residue a later sweep should retry.
# 'ready' and terminal 'failed' are excluded so re-running is idempotent; a stale
# 'generating' (a crashed prior run) is re-attempted.
_RETRYABLE_STATUSES = ("pending_retry", "generating")


def _now_utc():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


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


# ---------------------------------------------------------------------------
# Shared-seam helpers (Photo-seam Phase 1)
# ---------------------------------------------------------------------------

def _cache_key_for(brand: Optional[str], name: Optional[str], color: Optional[str]):
    """Product-identity cache key for the SHARED product_image_cache — BRANDED items only.

    The cache serves verified cards cross-user by product identity (brand+name+color).
    A branded photo item (e.g. a Uniqlo tee the user photographed) IS a mass-market
    product, so it may serve/reuse cached cards exactly like the Gmail path. An
    UNBRANDED photo garment has too weak an identity (name+color alone) — keying it
    would risk cross-user collisions AND would publish a card derived from one user's
    personal photo to another user. So: no brand -> no key -> no cache participation."""
    if not (brand or "").strip():
        return None
    return make_cache_key(brand, name, color)


def _maybe_promote_card(
    *, brand, name, color, url: Optional[str], content_sha256: Optional[str],
    verify_score: float,
) -> None:
    """Promote a VERIFIED generated card into the shared cache (branded items only)."""
    if not url or _cache_key_for(brand, name, color) is None:
        return
    promote_verified(
        brand=brand, name=name, color=color,
        image_url=url, content_sha256=content_sha256 or "",
        source_tier="generated", source_domain="generation",
        verify_score=verify_score,
    )


def _stamp_candidate_card_ready(
    db: Session, cand: IngestCandidate, url: str, *, storage_client=None
) -> None:
    """Write a VERIFIED card onto the candidate and drive the SHARED state machine.

    Same transition shape as the Gmail fill's success path: card fields + affirmative
    person_free (the pair-verify hard-fails person_present, so a stored card is
    person-free by construction) -> image_generated -> verified_clean -> and 'ready'
    ONLY via the shared mark_candidate_ready invariant (which also requires complete
    tags). A candidate with incomplete tags (no size for a sized category and no
    onboarding default) keeps its card but rests at 'verified_clean' — masked, never
    leaked. Caller commits.

    RAW-CROP PURGE (Photo-seam Phase 5): the moment the verified card lands, the raw
    source crop / uploaded reference has served its only purpose (generation
    reference) — the candidate's pointer is nulled so NO query can ever resolve to
    it again, and our own photo_items/ crop blob (+ its image_blobs dedup row) is
    deleted best-effort. Non-photo_items references (e.g. a manual add's uploaded
    reference in regenerate_refs/) are only unlinked, never deleted — the
    content-addressed blob store shares identical bytes across rows."""
    from datetime import datetime, timezone

    cand.generated_image_url = url
    cand.generation_status = "ready"
    cand.generation_attempts = 0  # verified success clears the failure ledger
    cand.person_status = "person_free"
    # A post-P2 generated card passed the verify-v2 invariant gates by construction.
    cand.invariant_checked_at = datetime.now(timezone.utc)
    advance(cand, "image_generated")
    advance(cand, "verified_clean")
    if not cand.size:
        facts = load_user_facts(db, cand.user_id)
        default = default_size_for_category((facts or {}).get("sizes"), cand.category)
        if default:
            cand.size = default
    if tags_ready(cand):
        mark_candidate_ready(cand)
    _purge_crop_reference(cand, storage_client)


def _purge_crop_reference(cand: IngestCandidate, storage_client) -> None:
    """Unlink (and, for our own crops, delete) the raw source image. Never raises."""
    crop_url = cand.image_url
    if not crop_url:
        return
    cand.image_url = None  # display-unreachable regardless of blob deletion outcome
    if "/photo_items/" not in crop_url:
        return  # foreign/shared reference — unlink only
    try:
        from app.utils.image_blob_store import delete_by_url

        deleted = bool(storage_client) and storage_client.delete_object(crop_url)
        delete_by_url(crop_url)
        logger.info(
            "crop purged cand=%s blob_deleted=%s", cand.id, deleted
        )
    except Exception as exc:
        logger.warning("crop purge failed (%s) cand=%s", type(exc).__name__, cand.id)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def generation_armed() -> bool:
    """True when generation CAN run: a ladder provider key + a verify key present.

    Photo-seam Phase 1: delegates to the ONE shared definition in generate_core (same
    ladder, same verify key requirement). The route uses it to decide whether to defer
    run-completion + dispatch the job (vs. finalize at commit and leave cards as raw
    cutouts when generation isn't set up)."""
    return _core_generation_armed()


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
    ladder = tuple(provider_ladder) if provider_ladder else None  # None -> the shared core ladder
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
    ladder: Optional[Sequence[str]],
    gen_budget: GenerationBudget,
    verify_budget: VerifyBudget,
    usage: UsageAccumulator,
) -> _CandidateOutcome:
    """Produce ONE candidate's verified card via the SHARED seam, in its OWN DB session.

    Photo-seam Phase 1: the generate→verify→store work is generate_core.
    generate_from_reference_bytes — the exact seam the Gmail on-model path runs — so the
    ladder, the mandatory pair-verify (person backstop + garment/color/pattern/logo
    fidelity) and card storage are defined ONCE. This worker owns only the photo state
    machine: cache-first, 'generating' mark, outcome mapping, atomic run counters.
    Never raises — any failure holds the candidate for a later retry sweep."""
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

        # CACHE-FIRST (shared product_image_cache, same as the Gmail fill): a BRANDED
        # photo item is a mass-market product — an identical product generated/verified
        # once (by any user, either pipeline) serves again at zero cost. Unbranded
        # personal garments never participate (see _cache_key_for).
        cached = lookup_verified(_cache_key_for(cand.brand, cand.name, cand.color))
        if cached:
            _stamp_candidate_card_ready(db, cand, cached, storage_client=storage_client)
            db.query(IngestRun).filter(IngestRun.sync_id == sync_id).update(
                {IngestRun.generation_ready: IngestRun.generation_ready + 1},
                synchronize_session=False,
            )
            db.commit()
            return _CandidateOutcome("ready", 0.0)

        # Fast-path skip when the SHARED budget is already spent (cost cut #3): don't
        # churn a 'generating' write + cutout download we can't act on. The authoritative
        # per-CALL take() lives inside the shared core's rung loop.
        # Phase 3 strand-kill: leave HEAL-ELIGIBLE residue ('pending_retry' +
        # 'image_pending'), never a bare staged/NULL row nothing re-selects — the
        # settle condition must stay reachable via the self-heal sweep.
        if gen_budget.remaining <= 0:
            cand.generation_status = "pending_retry"
            advance(cand, "image_pending")
            db.commit()
            return _CandidateOutcome("budget")

        # Mark 'generating' and stream it immediately (the deck renders the loading state).
        cand.generation_status = "generating"
        cand.pipeline_state = "image_pending"  # ready-first: awaiting its generated card
        db.commit()

        dl = _download_bytes(cand.image_url)
        if dl is None:
            _hold(db, cand, sync_id, count_attempt=False)  # transient -> no ceiling bump
            return _CandidateOutcome("download_error")
        ref_bytes, ref_ct = dl

        g = generate_from_reference_bytes(
            reference_bytes=ref_bytes,
            reference_content_type=ref_ct,
            name=cand.name,
            category=cand.category,
            color=cand.color,
            brand=cand.brand,
            pattern=None,  # no pattern column on ingest_candidates
            storage_client=storage_client,
            user_id=cand.user_id,
            gen_budget=gen_budget,
            verify_budget=verify_budget,
            usage=usage,
            ladder=ladder,
        )

        if g.outcome == "ready" and g.url:
            # Candidate write + atomic counter increment in ONE transaction. The
            # `generation_ready = generation_ready + 1` runs as a single SQL UPDATE, so
            # concurrent workers can't lose an increment (row-level lock serializes them).
            _stamp_candidate_card_ready(db, cand, g.url, storage_client=storage_client)
            db.query(IngestRun).filter(IngestRun.sync_id == sync_id).update(
                {IngestRun.generation_ready: IngestRun.generation_ready + 1},
                synchronize_session=False,
            )
            db.commit()
            _maybe_promote_card(
                brand=cand.brand, name=cand.name, color=cand.color,
                url=g.url, content_sha256=g.content_sha256,
                verify_score=g.verify_score,
            )
            return _CandidateOutcome("ready", g.cost_usd)

        if g.outcome == "budget":
            # Budget ran out before any generation call (race with concurrent workers).
            # Phase 3 strand-kill: 'pending_retry' + 'image_pending' — heal-eligible
            # residue the self-heal sweep re-selects (the old staged/NULL revert was
            # re-selected by NOTHING and stranded the batch forever). NOT counted as a
            # failed attempt (nothing was generated/verified).
            cand.generation_status = "pending_retry"
            # pipeline_state is already 'image_pending' (set at the 'generating' mark).
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
    # Ready-first: terminal 'failed' leaves the machine at 'failed' (excluded from the
    # deck AND from blocking the banner); a retryable hold stays 'image_pending'.
    cand.pipeline_state = (
        "failed" if cand.generation_status == "failed" else "image_pending"
    )
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
    content_sha256: Optional[str] = None  # for the shared-cache promote
    verify_score: float = 0.0


def _generate_from_crop(
    *,
    crop_url: str,
    name: Optional[str],
    category: Optional[str],
    color: Optional[str],
    brand: Optional[str],
    storage_client,
    user_id: UUID,
    ladder: Optional[Sequence[str]],
    gen_budget: GenerationBudget,
    verify_budget: VerifyBudget,
    usage: UsageAccumulator,
    steering: Optional[str] = None,
) -> _HealOutcome:
    """Fetch a stored crop and run it through the ONE shared generate→verify→store seam.

    Photo-seam Phase 1: this is now a thin URL→bytes adapter over
    generate_core.generate_from_reference_bytes (the same seam the Gmail on-model path
    runs) — same ladder, same MANDATORY pair-verify (a skipped/disabled verify is never
    a pass), same card storage. Makes NO DB writes (the caller persists), so it's
    reusable for candidates, confirmed items and Regenerate.

    ``steering`` is an OPTIONAL untrusted user correction (Regenerate reason). It is
    fenced inside the prompt (prompt._steering_clause) and NEVER relaxes the verify gate —
    a steered generation still has to pass verify against the crop, so a reason cannot
    force a hallucinated result through.

    BUDGET COUNTS CALLS (cost cut #3): the shared core consumes gen_budget.take() once
    per ACTUAL provider call, and the SHARED budget passed in by the caller means
    self-heal draws from the SAME bounded pool as the main pass — never a fresh 50."""
    if gen_budget.remaining <= 0:
        return _HealOutcome("budget")
    dl = _download_bytes(crop_url)
    if dl is None:
        return _HealOutcome("download_error")
    ref_bytes, ref_ct = dl
    g = generate_from_reference_bytes(
        reference_bytes=ref_bytes,
        reference_content_type=ref_ct,
        name=name,
        category=category,
        color=color,
        brand=brand,
        pattern=None,
        storage_client=storage_client,
        user_id=user_id,
        gen_budget=gen_budget,
        verify_budget=verify_budget,
        usage=usage,
        steering=steering,
        ladder=ladder,
    )
    # 'budget' = denied before any call (caller stops the sweep); 'held' = a real
    # attempt missed (caller bumps the item's attempt ceiling); 'ready' carries the
    # stored URL + sha/score for the shared-cache promote.
    return _HealOutcome(
        g.outcome, url=g.url, cost_usd=g.cost_usd,
        content_sha256=g.content_sha256, verify_score=g.verify_score,
    )


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
        ladder = tuple(provider_ladder) if provider_ladder else None  # None -> shared core ladder
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
            # Shared cache-first (branded products only — see _cache_key_for).
            cached = lookup_verified(_cache_key_for(c.brand, c.name, c.color))
            if cached:
                _stamp_candidate_card_ready(db, c, cached, storage_client=storage_client)
                db.commit()
                stats.ready += 1
                continue
            r = _heal(c.image_url, c.name, c.category, c.color, c.brand)
            if r.outcome == "budget":
                stats.budget_stopped = True
                break
            if r.outcome == "download_error":
                stats.download_errors += 1
                stats.held += 1
                continue
            if r.url:
                # Verified card + the SHARED state machine (ready only via the shared
                # mark_candidate_ready invariant; incomplete tags rest at verified_clean).
                _stamp_candidate_card_ready(db, c, r.url, storage_client=storage_client)
                db.commit()
                _maybe_promote_card(
                    brand=c.brand, name=c.name, color=c.color, url=r.url,
                    content_sha256=r.content_sha256, verify_score=r.verify_score,
                )
                stats.ready += 1
                stats.cost_usd += r.cost_usd
            else:
                # Real generate->verify miss: bump the attempt ceiling; terminal at N.
                c.generation_attempts = (c.generation_attempts or 0) + 1
                c.generation_status = _next_failure_status(c.generation_attempts)
                c.pipeline_state = (
                    "failed" if c.generation_status == "failed" else "image_pending"
                )
                db.commit()
                stats.held += 1

        # --- confirmed items: the card IS image_url, so success replaces it --------
        if not stats.budget_stopped:
            for it in item_rows:
                cached = lookup_verified(_cache_key_for(it.brand, it.name, it.color_primary))
                if cached:
                    it.image_url = cached
                    it.generation_status = "ready"
                    it.generation_attempts = 0
                    it.person_status = "person_free"  # cached cards are verified person-free
                    it.invariant_checked_at = _now_utc()
                    db.commit()
                    stats.ready += 1
                    continue
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
                    # Ready-first: the verified card replacing the crop is person-free.
                    it.person_status = "person_free"
                    it.invariant_checked_at = _now_utc()
                    db.commit()
                    _maybe_promote_card(
                        brand=it.brand, name=it.name, color=it.color_primary, url=r.url,
                        content_sha256=r.content_sha256, verify_score=r.verify_score,
                    )
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

        ladder = tuple(provider_ladder) if provider_ladder else None  # None -> shared core ladder
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
            new_sha, new_score = r.content_sha256, r.verify_score
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
            new_sha, new_score = g.content_sha256, g.verify_score

        if new_url:
            item.image_url = new_url
            item.generation_status = "ready"
            item.generation_attempts = 0  # verified success clears the failure ledger
            # Ready-first: regeneration output passed the verified person-free gate.
            item.person_status = "person_free"
            item.invariant_checked_at = _now_utc()
            db.commit()
            # Shared-cache promote (branded products only): a freshly verified card for
            # this product identity serves future lookups across both pipelines.
            _maybe_promote_card(
                brand=item.brand, name=item.name, color=item.color_primary,
                url=new_url, content_sha256=new_sha, verify_score=new_score,
            )
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


# ---------------------------------------------------------------------------
# Manual-add generation (Photo-seam Phase 4) — the typed manual entry point runs
# the SAME seam: candidate -> generate (ref or t2i) -> verify v2 -> card ->
# shared readiness -> THE confirm chokepoint (auto-confirm; the user already
# typed/approved the fields, so no deck stop unless something needs attention).
# ---------------------------------------------------------------------------

def run_manual_generation(
    user_id: UUID,
    db: Session,
    sync_id: UUID,
    *,
    storage_client=None,
    gen_budget: Optional[GenerationBudget] = None,
) -> GenerationStats:
    """Produce the invariant-compliant card for a manual add's candidate(s), then
    auto-confirm each 'ready' one through the confirm chokepoint. Never raises.

    Reference-conditioned (generate_from_reference_bytes) when the user attached an
    image, t2i (generate_from_text) from the typed attributes otherwise — both via
    the ONE shared core with the mandatory verify-v2 gate. Retries INLINE up to the
    attempt ceiling so a manual batch always leaves terminal (ready|failed) or
    heal-eligible residue — the settle condition stays reachable. A 'ready' candidate
    whose tags are incomplete (needs-size) is NOT auto-confirmed: it surfaces in the
    review deck via the shared needs-size rule."""
    stats = GenerationStats(user_id=user_id, sync_id=sync_id)
    run = (
        db.query(IngestRun)
        .filter(IngestRun.sync_id == sync_id, IngestRun.user_id == user_id)
        .first()
    )
    try:
        targets = (
            db.query(IngestCandidate)
            .filter(
                IngestCandidate.user_id == user_id,
                IngestCandidate.sync_id == sync_id,
                IngestCandidate.source_type == "manual",
                IngestCandidate.status == "pending",
                IngestCandidate.generation_attempts < settings.GENERATION_MAX_ATTEMPTS,
                or_(
                    IngestCandidate.generation_status.is_(None),
                    IngestCandidate.generation_status.in_(_RETRYABLE_STATUSES),
                ),
            )
            .order_by(IngestCandidate.created_at.asc())
            .all()
        )
        stats.targets = len(targets)
        if run is not None:
            run.generation_total = len(targets)
            run.generation_ready = 0
            run.generation_failed = 0
            db.commit()

        if storage_client is None:
            storage_client = _storage_from_env()
        if gen_budget is None:
            gen_budget = GenerationBudget(settings.GENERATION_MAX_PER_RUN)
        verify_budget = VerifyBudget(settings.GMAIL_VERIFY_MAX_PER_RUN)
        usage = UsageAccumulator()

        for cand in targets:
            outcome = _generate_manual_candidate(
                db, cand, sync_id, storage_client, gen_budget, verify_budget, usage,
            )
            if outcome == "ready":
                stats.ready += 1
                if cand.pipeline_state == "ready":
                    _auto_confirm_manual(db, user_id, cand)
            elif outcome == "budget":
                stats.budget_stopped = True
            else:
                stats.held += 1

        record_fill_usage(db, sync_id, usage)
    except Exception as exc:
        logger.error("run_manual_generation sync=%s: %s", sync_id, type(exc).__name__)
    finally:
        _finalize_run(db, run)

    logger.info(
        "manual generation done sync=%s user=%s: targets=%d ready=%d held=%d "
        "budget_stopped=%s",
        sync_id, user_id, stats.targets, stats.ready, stats.held, stats.budget_stopped,
    )
    return stats


def _generate_manual_candidate(
    db: Session,
    cand: IngestCandidate,
    sync_id: UUID,
    storage_client,
    gen_budget: GenerationBudget,
    verify_budget: VerifyBudget,
    usage: UsageAccumulator,
) -> str:
    """One manual candidate through the shared seam, retried inline to the ceiling.

    Returns 'ready' | 'held' (terminal or residue) | 'budget' | 'download_error'.
    Counters: generation_ready/_failed are bumped ONCE per candidate outcome (not per
    inline retry) so the status pill's denominators stay honest."""
    from app.services.image_generation.generate_core import generate_from_text

    # Shared cache-first (branded products only — see _cache_key_for).
    cached = lookup_verified(_cache_key_for(cand.brand, cand.name, cand.color))
    if cached:
        _stamp_candidate_card_ready(db, cand, cached, storage_client=storage_client)
        db.query(IngestRun).filter(IngestRun.sync_id == sync_id).update(
            {IngestRun.generation_ready: IngestRun.generation_ready + 1},
            synchronize_session=False,
        )
        db.commit()
        return "ready"

    while (cand.generation_attempts or 0) < settings.GENERATION_MAX_ATTEMPTS:
        if gen_budget.remaining <= 0:
            # Heal-eligible residue (Phase 3 strand-kill shape); the status-poll
            # kick re-runs this pass.
            cand.generation_status = "pending_retry"
            advance(cand, "image_pending")
            db.commit()
            return "budget"

        cand.generation_status = "generating"
        cand.pipeline_state = "image_pending"
        db.commit()

        if cand.image_url:
            # User-attached reference: conditions IDENTITY only, verified pairwise.
            dl = _download_bytes(cand.image_url)
            if dl is None:
                cand.generation_status = "pending_retry"  # transient: no ceiling burn
                db.commit()
                db.query(IngestRun).filter(IngestRun.sync_id == sync_id).update(
                    {IngestRun.generation_failed: IngestRun.generation_failed + 1},
                    synchronize_session=False,
                )
                db.commit()
                return "download_error"
            ref_bytes, ref_ct = dl
            g = generate_from_reference_bytes(
                reference_bytes=ref_bytes, reference_content_type=ref_ct,
                name=cand.name, category=cand.category, color=cand.color,
                brand=cand.brand, pattern=None,
                storage_client=storage_client, user_id=cand.user_id,
                gen_budget=gen_budget, verify_budget=verify_budget, usage=usage,
            )
        else:
            # No reference at all: t2i from the typed attributes (verify v2 gates
            # single-item/off-white/framing/person at the caller inside the core).
            g = generate_from_text(
                name=cand.name, category=cand.category, color=cand.color,
                brand=cand.brand,
                storage_client=storage_client, user_id=cand.user_id,
                gen_budget=gen_budget, verify_budget=verify_budget, usage=usage,
            )

        if g.outcome == "ready" and g.url:
            _stamp_candidate_card_ready(db, cand, g.url, storage_client=storage_client)
            db.query(IngestRun).filter(IngestRun.sync_id == sync_id).update(
                {IngestRun.generation_ready: IngestRun.generation_ready + 1},
                synchronize_session=False,
            )
            db.commit()
            _maybe_promote_card(
                brand=cand.brand, name=cand.name, color=cand.color,
                url=g.url, content_sha256=g.content_sha256, verify_score=g.verify_score,
            )
            return "ready"
        if g.outcome == "budget":
            cand.generation_status = "pending_retry"
            db.commit()
            return "budget"
        # Real generate->verify miss: burn one attempt and retry inline.
        cand.generation_attempts = (cand.generation_attempts or 0) + 1
        cand.generation_status = _next_failure_status(cand.generation_attempts)
        cand.pipeline_state = (
            "failed" if cand.generation_status == "failed" else "image_pending"
        )
        db.commit()

    db.query(IngestRun).filter(IngestRun.sync_id == sync_id).update(
        {IngestRun.generation_failed: IngestRun.generation_failed + 1},
        synchronize_session=False,
    )
    db.commit()
    return "held"


def _auto_confirm_manual(db: Session, user_id: UUID, cand: IngestCandidate) -> None:
    """Bear the manual item through THE confirm chokepoint (no parallel insert).

    The user already typed/approved every field, so a fully-'ready' manual candidate
    skips the deck stop. Best-effort: a refusal (should not happen for 'ready') just
    leaves the candidate reviewable in the deck. Enrichment parity with the old
    direct insert: the enricher runs for the newborn item."""
    from app.gmail_closet.review_service import ConfirmError, confirm_candidates

    try:
        result = confirm_candidates(db, user_id, accepted=[str(cand.id)])
    except ConfirmError as exc:
        logger.info(
            "manual auto-confirm deferred user=%s cand=%s (%s)", user_id, cand.id, exc
        )
        return
    item_ids = [w.clothing_item_id for w in result.written]
    if item_ids:
        try:
            from app.services.enrichment import enrich_items_background

            enrich_items_background(str(user_id), item_ids)
        except Exception as exc:  # enrichment is best-effort, never blocks the birth
            logger.warning("manual enrich failed (%s)", type(exc).__name__)
    logger.info("manual item born user=%s cand=%s items=%d", user_id, cand.id, len(item_ids))


def manual_generate_background(user_id_str: str, sync_id_str: str) -> None:
    """BackgroundTasks entry point for a manual add (mirrors generate_background):
    own DB session, shared per-run budget, never raises."""
    from app.db import SessionLocal  # late import avoids a module-level import cycle

    db = SessionLocal()
    try:
        run_manual_generation(
            UUID(user_id_str), db, UUID(sync_id_str),
            gen_budget=GenerationBudget(settings.GENERATION_MAX_PER_RUN),
        )
    except Exception as exc:
        logger.error("manual_generate_background: %s: %s", type(exc).__name__, exc)
    finally:
        db.close()


def self_heal_background(user_id_str: str) -> None:
    """BackgroundTasks entry point for the poll-kicked strand heal (Phase 3).

    Own DB session, never raises. Re-attempts the user's 'pending_retry' residue
    across ALL syncs (exclude_sync_id=None — the poll kicks precisely because THIS
    sync has stragglers). Idempotent + budget-capped like every sweep."""
    from app.db import SessionLocal  # late import avoids a module-level import cycle

    db = SessionLocal()
    try:
        run_generation_self_heal(UUID(user_id_str), db, exclude_sync_id=None)
    except Exception as exc:
        logger.error("self_heal_background: %s: %s", type(exc).__name__, exc)
    finally:
        db.close()


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
