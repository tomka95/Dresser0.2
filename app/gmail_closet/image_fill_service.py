"""Phase 4 background image fill + cross-user self-heal.

WHY THIS EXISTS
---------------
Extraction now resolves only the FAST image tiers (inline / email-img / cache) so the
swipe deck appears immediately. The SLOW tiers (og:image / feed / search) are real
outbound work and would block the deck, so they run HERE, in a background pass that
streams images onto the still-imageless candidates after the deck is shown. The SAME
pass also SELF-HEALS: it re-resolves pending items — both swipe candidates and already
confirmed clothing_items — CACHE-FIRST, so an item another user has already resolved
into the shared product_image_cache fills instantly at ~0 cost.

WHAT IT DOES (per target — a pending ingest_candidate or a pending clothing_item)
---------------------------------------------------------------------------------
  1. CACHE-FIRST (no network, no email): look the product up in the shared, verified
     product_image_cache. A hit fills image_url + image_status='resolved' for free.
  2. SLOW RESOLVE (only the residue, only if storage + a Gmail token are available):
     re-fetch the source email (trusted Gmail API), run the resolver's SLOW tiers
     (cache -> og:image -> feed -> search, every remote hop SSRF-guarded and
     vision-verified). A hit -> 'resolved'; the tiers exhausted with nothing found ->
     'placeholder' (terminal; the deck stops polling it). A transient email re-fetch
     error or an exhausted per-run budget leaves the target 'pending' for a later run.

SAFETY / COST
-------------
Idempotent (keys off image_status='pending'/null + a null image_url; re-running finds
nothing new). Budget-capped: the per-run Verify / Fetch / Search budgets are shared
across the whole pass, and the loop stops issuing email fetches once the fetch budget
is spent. The verify gate is intact on EVERY tier — no unverified image is ever
committed, so a card never shows a wrong/unverified image mid-resolve. Subjects/bodies
are never logged; only ids, tiers, and counts.

ENTRY POINTS
------------
  run_image_fill(user_id, db, ...)  -- one user; called at the tail of the ingest
                                       pipeline (after the deck shows) and by the dev
                                       self-heal script.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional
from uuid import UUID

import httpx

from app.core.config import settings
from app.gmail_closet.fetch_service import _fetch_one
from app.gmail_closet.gmail_oauth_service import ensure_fresh_token
from app.gmail_closet.image_guard import FetchBudget, GuardRejection, guarded_fetch, is_allowlisted_host
from app.gmail_closet.image_resolver import (
    ALL_TIERS,
    ResolvedImageCache,
    ResolverItem,
    resolve_item_images,
)
from app.gmail_closet.image_verify import VerifyBudget, verify_image
from app.gmail_closet.product_image_cache import lookup_verified, make_cache_key, promote_verified
from app.gmail_closet.shopping_search import SearchBudget
from app.platform.usage import UsageAccumulator, record_fill_usage
from app.services.closet_canonicalize import load_user_facts
from app.services.readiness import (
    TERMINAL_STATES as _TERMINAL_STATES,
    STORED_IMAGE_STATUSES as _STORED_IMAGE_STATUSES,
    advance as _advance,
    apply_canonicalized as _apply_canonicalized,
    mark_candidate_ready,
    tags_ready as _tags_ready,
)
from app.services.image_generation.base import GenerationBudget
from app.models import ClothingItem, GoogleAccount, IngestCandidate

logger = logging.getLogger(__name__)

# Tiers tried for a SOURCELESS target (a confirmed item with no source email): no DOM
# to read, so inline/email-img/og can't run — only the brand+name+color tiers do.
_SOURCELESS_TIERS = frozenset({"feed", "search"})


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def _now_utc():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


@dataclass
class ImageFillStats:
    """Redaction-safe summary of one background image-fill run (no email content)."""
    user_id: UUID
    candidates_seen: int = 0
    confirmed_seen: int = 0
    cache_filled: int = 0          # filled by the shared cross-user cache (~0 cost)
    slow_filled: int = 0           # filled by a slow tier (og:image / feed / search)
    generated: int = 0             # Wave B: on-model routed OR t2i-from-attributes -> 'resolved'
    exhausted: int = 0             # slow tiers ran + generation missed -> 'placeholder'
    fetch_errors: int = 0          # source email could not be re-fetched (left pending)
    budget_stopped: bool = False   # a per-run budget capped the pass (rest left pending)
    # Ready-first Phase 2 counters (all redaction-safe counts):
    person_checked: int = 0        # affirmative person verdicts written (free OR present)
    person_routed: int = 0         # person_present images routed through generation
    ready: int = 0                 # candidates driven to pipeline_state='ready'
    failed: int = 0                # candidates driven to terminal pipeline_state='failed'
    tier_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    elapsed: float = 0.0

    @property
    def filled(self) -> int:
        return self.cache_filled + self.slow_filled


# ---------------------------------------------------------------------------
# Normalized fill target (an ingest_candidate or a clothing_item — both carry
# image_url + image_status, so writes are uniform)
# ---------------------------------------------------------------------------

@dataclass
class _Target:
    row: object                    # IngestCandidate | ClothingItem
    name: str
    brand: Optional[str]
    color: Optional[str]
    size: Optional[str]
    unit_price: Optional[float]
    category: Optional[str]
    message_id: Optional[str]      # source email for the SLOW (og/search) re-fetch


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _candidate_target(c: IngestCandidate) -> _Target:
    return _Target(
        row=c, name=c.name or "", brand=c.brand, color=c.color, size=c.size,
        unit_price=_to_float(c.unit_price), category=c.category, message_id=c.message_id,
    )


def _clothing_target(it: ClothingItem) -> _Target:
    return _Target(
        row=it, name=it.name or "", brand=it.brand, color=it.color_primary, size=it.size,
        unit_price=_to_float(it.unit_price), category=it.category,
        message_id=it.source_message_id,
    )


def _resolver_item(t: _Target) -> ResolverItem:
    return ResolverItem(
        name=t.name, unit_price=t.unit_price, color=t.color, size=t.size,
        brand=t.brand, category=t.category,
    )


# ---------------------------------------------------------------------------
# Ready-first Phase 2: the candidate state machine driver
# ---------------------------------------------------------------------------
# Photo-seam Phase 1: the machine itself (advance / tags_ready / apply_canonicalized /
# mark_candidate_ready and the state constants) moved to the NEUTRAL shared module
# app.services.readiness — ONE definition for both pipelines. This module keeps only
# its gmail-specific terminal stamper (_stamp_final) and imports the rest (aliased
# above so existing tests/callers keep their names).


def _stamp_final(cand: IngestCandidate, stats: ImageFillStats) -> None:
    """Terminal-state decision for one Gmail candidate at the end of a fill pass.

    ready    <- person_free + stored image + complete tags (via mark_candidate_ready)
    failed   <- image tiers exhausted ('placeholder'), or a person_present image whose
                generation burned the attempt ceiling (unrecoverable: the raw image can
                never be shown, and no clean card could be produced)
    residue  <- stays at its in-flight state ('image_pending'), masked, retried later
    """
    if cand.pipeline_state in _TERMINAL_STATES:
        return
    if cand.image_status == "placeholder":
        cand.pipeline_state = "failed"
        stats.failed += 1
        return
    if (
        cand.person_status == "person_present"
        and (cand.generation_attempts or 0) >= settings.GENERATION_MAX_ATTEMPTS
    ):
        cand.pipeline_state = "failed"
        stats.failed += 1
        return
    if (
        cand.image_url
        and cand.person_status == "person_free"
        and (cand.image_status or "") in _STORED_IMAGE_STATUSES
    ):
        _advance(cand, "verified_clean")
        if _tags_ready(cand):
            mark_candidate_ready(cand)
            stats.ready += 1
        return
    _advance(cand, "image_pending")


def _reconcile_person(
    db,
    cands: List[IngestCandidate],
    *,
    user_id: UUID,
    http: Optional[httpx.Client],
    storage_client,
    gen_budget: GenerationBudget,
    verify_budget: VerifyBudget,
    fetch_budget: FetchBudget,
    usage: Optional[UsageAccumulator],
    stats: ImageFillStats,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> None:
    """Affirmative person check for Gmail candidates that HAVE an image but an
    'unknown' person_status (the Break-A gap: images stored before any person
    detection existed, plus fresh cache-tier fills which are not re-verified).

    Per candidate: guarded-fetch the stored image bytes -> verify_image ->
      * person-free  -> person_status='person_free' (the image may now surface)
      * person present -> person_status='person_present' (recorded, stays masked) and
        route through generate_from_reference_bytes; a verified card REPLACES the
        image; a real miss bumps generation_attempts (terminal at the ceiling)
      * wrong image (verify ran, matches=False) -> drop it back to 'pending' so the
        resolver tiers find a correct one on a later pass
      * verify skipped (budget/disabled/error) -> stays 'unknown' -> stays masked
    Fail-closed at every branch: an unchecked or person image can never surface."""
    if not cands or http is None:
        return
    from app.services.image_generation.generate_core import (
        generate_from_reference_bytes,
        generation_armed,
    )

    can_generate = storage_client is not None and generation_armed()

    for cand in cands:
        if should_cancel is not None and should_cancel():
            stats.budget_stopped = True
            break
        if fetch_budget.remaining <= 0:
            stats.budget_stopped = True
            break
        host = httpx.URL(cand.image_url).host or ""
        profile = "retailer" if is_allowlisted_host(host) else "open"
        try:
            fetched = guarded_fetch(
                http, cand.image_url, kind="image", profile=profile, fetch_budget=fetch_budget
            )
        except GuardRejection as exc:
            logger.info("person-reconcile fetch refused host=%s reason=%s", exc.host, exc.reason)
            continue  # leave 'unknown' -> masked; a later pass retries
        except Exception as exc:
            logger.warning("person-reconcile fetch error (%s)", type(exc).__name__)
            continue

        verdict = verify_image(
            image_bytes=fetched.content, content_type=fetched.content_type,
            category=cand.category, color=cand.color, name=cand.name,
            budget=verify_budget, usage=usage,
        )
        if getattr(verdict, "skipped", False):
            continue  # no affirmative verdict -> stays 'unknown' -> stays masked
        if not verdict.matches:
            # The stored image is WRONG for this item — drop it so the resolver tiers
            # re-resolve on a later pass; fail-closed in the meantime.
            cand.image_url = None
            cand.image_status = "pending"
            db.commit()
            continue

        stats.person_checked += 1
        if not getattr(verdict, "person_present", False):
            cand.person_status = "person_free"
            db.commit()
            continue

        # Person in frame: record the affirmative verdict (never 'unknown' once
        # checked), keep masked, and route through clean generation.
        cand.person_status = "person_present"
        db.commit()
        stats.person_routed += 1
        if not can_generate:
            continue  # masked; generation phase picks it up when armed
        g = generate_from_reference_bytes(
            reference_bytes=fetched.content,
            reference_content_type=fetched.content_type,
            name=cand.name, category=cand.category, color=cand.color, brand=cand.brand,
            storage_client=storage_client, user_id=user_id,
            gen_budget=gen_budget, verify_budget=verify_budget, usage=usage,
        )
        if g.outcome == "ready" and g.url:
            _advance(cand, "image_generated")
            cand.image_url = g.url          # the verified person-free card REPLACES it
            cand.image_status = "resolved"
            cand.person_status = "person_free"
            cand.invariant_checked_at = _now_utc()  # v2-gated card by construction
            if hasattr(cand, "generation_provider"):
                cand.generation_provider = g.provider
                cand.generation_cost_usd = g.cost_usd
            promote_verified(
                brand=cand.brand, name=cand.name, color=cand.color,
                image_url=g.url, content_sha256=g.content_sha256 or "",
                source_tier="generated", source_domain="generation",
                verify_score=g.verify_score,
            )
            stats.generated += 1
            stats.tier_counts["generated"] += 1
            db.commit()
        elif g.outcome == "held":
            # A real generate->verify miss burns one attempt (terminal at the ceiling).
            cand.generation_attempts = (cand.generation_attempts or 0) + 1
            db.commit()
        else:  # 'budget' — shared ceiling hit; stop the pass, later run resumes
            stats.budget_stopped = True
            break


# ---------------------------------------------------------------------------
# The fill engine (cache-first, then email-based slow resolve)
# ---------------------------------------------------------------------------

def _maybe_t2i(t, storage_client, user_id, gen_budget, verify_budget, usage) -> Optional[str]:
    """Text->image product image from a target's attributes (Wave B / Fix 4).

    The LAST rung of the image fallback ladder — reached only when no source image
    resolved. Runs ONLY when a gen_budget is supplied (background pass), storage is
    available, and generation is armed; the image must pass verify_image AND be person-free
    (enforced in generate_from_text). Returns a stored URL or None. Lazy import keeps this
    gmail_closet module free of a top-level provider/services import."""
    if gen_budget is None or storage_client is None:
        return None
    from app.services.image_generation.generate_core import (
        generate_from_text,
        generation_armed,
    )

    if not generation_armed():
        return None
    out = generate_from_text(
        name=t.name, category=t.category, color=t.color, brand=t.brand,
        storage_client=storage_client, user_id=user_id,
        gen_budget=gen_budget, verify_budget=verify_budget, usage=usage,
    )
    if out.outcome != "ready" or not out.url:
        return None
    # Promote the verified t2i card into the shared cache (source_tier='generated') so an
    # identical mass-market item is generated ONCE ever — the cache-first pass serves it
    # cross-user at ~0 cost and a crash-resumed run never re-bills the same product.
    promote_verified(
        brand=t.brand, name=t.name, color=t.color,
        image_url=out.url, content_sha256=out.content_sha256 or "",
        source_tier="generated", source_domain="generation",
        verify_score=out.verify_score,
    )
    return out.url


def _resolve_targets(
    db,
    targets: List[_Target],
    *,
    user_id: UUID,
    token: Optional[str],
    http: Optional[httpx.Client],
    storage_client,
    cache: ResolvedImageCache,
    verify_budget: VerifyBudget,
    fetch_budget: FetchBudget,
    search_budget: SearchBudget,
    usage: Optional[UsageAccumulator],
    stats: ImageFillStats,
    should_cancel: Optional[Callable[[], bool]] = None,
    gen_budget: Optional[GenerationBudget] = None,
) -> None:
    """Fill image_url/image_status for ``targets`` in place. Cache-first, then slow.

    ``should_cancel`` is checked before each SLOW source-email tier (the minutes-
    long og:image / feed / search work). On cancel the loop stops and leaves the
    remaining targets 'pending' — identical to the budget-exhausted path, so a
    later run's self-heal fills them. Default None -> never cancels."""
    if not targets:
        return

    # --- Pass 1: CACHE-FIRST (no network) — the cheap cross-user self-heal --------
    residue: List[_Target] = []
    for t in targets:
        ck = make_cache_key(t.brand, t.name, t.color)
        url = lookup_verified(ck) if ck else None
        if url:
            t.row.image_url = url
            t.row.image_status = "resolved"
            stats.cache_filled += 1
            stats.tier_counts["cache"] += 1
        else:
            residue.append(t)
    db.commit()

    # The slow tiers need to upload resolved bytes (storage) and re-fetch the source
    # email (token + http). Without either, the cache pass is all we can safely do —
    # leave the residue 'pending' so a later run (or a future cache seed) fills it.
    if not residue or storage_client is None or token is None or http is None:
        return

    by_msg: Dict[str, List[_Target]] = defaultdict(list)
    sourceless: List[_Target] = []
    for t in residue:
        (by_msg[t.message_id] if t.message_id else sourceless).append(t)

    # --- Pass 2: SLOW tiers per source email (og:image / feed / search) ----------
    for msg_id, group in by_msg.items():
        if should_cancel is not None and should_cancel():
            # Graceful worker shutdown: stop promptly, leave the rest 'pending'
            # (same as budget-exhausted) so a later self-heal run fills them.
            stats.budget_stopped = True
            break
        if fetch_budget.remaining <= 0:
            stats.budget_stopped = True
            break  # leave the rest 'pending' for a later run (NOT 'placeholder')
        raw = _fetch_one(http, token, msg_id)
        if raw is None:
            stats.fetch_errors += 1
            continue  # transient re-fetch failure -> leave 'pending', retry later
        payload = raw.get("payload", {})
        resolved = resolve_item_images(
            payload=payload,
            items=[_resolver_item(t) for t in group],
            client=http,
            token=token,
            msg_id=msg_id,
            storage_client=storage_client,
            cache=cache,
            user_id=user_id,
            verify_budget=verify_budget,
            fetch_budget=fetch_budget,
            search_budget=search_budget,
            # Extraction no longer resolves images, so the fill runs the FULL waterfall
            # (inline/email-img/cache/og/feed/search) on the re-fetched email.
            tiers=ALL_TIERS,
            usage=usage,
            # Wave B: on-model images resolve to a generated product-only card (resolver
            # tier 'generated'); background-only, so it's passed only from this slow pass.
            gen_budget=gen_budget,
        )
        for t, r in zip(group, resolved):
            if r.stored_url:
                t.row.image_url = r.stored_url
                t.row.image_status = "resolved"
                # Ready-first Phase 2: persist the resolver's AFFIRMATIVE person verdict
                # (person_free from a real verify pass / a generated card). None (cache
                # hit, verify disabled) keeps the fail-closed 'unknown' — the reconcile
                # pass person-checks those before anything can surface.
                if r.person and hasattr(t.row, "person_status"):
                    t.row.person_status = r.person
                    stats.person_checked += 1
                if r.tier == "generated":
                    # A generated card passed the verify-v2 invariant gates by construction.
                    if hasattr(t.row, "invariant_checked_at"):
                        t.row.invariant_checked_at = _now_utc()
                    stats.generated += 1
                else:
                    stats.slow_filled += 1
                stats.tier_counts[r.tier] += 1
                continue
            # No source image resolved -> generate a product image from attributes (t2i),
            # verified + person-free, BEFORE falling back to a placeholder.
            gen_url = _maybe_t2i(t, storage_client, user_id, gen_budget, verify_budget, usage)
            if gen_url:
                t.row.image_url = gen_url
                t.row.image_status = "resolved"
                if hasattr(t.row, "person_status"):
                    # t2i output is person-free by construction (generate_from_text
                    # hard-requires person_present=false on its verify).
                    t.row.person_status = "person_free"
                    stats.person_checked += 1
                if hasattr(t.row, "invariant_checked_at"):
                    t.row.invariant_checked_at = _now_utc()
                stats.generated += 1
                stats.tier_counts["generated"] += 1
            else:
                t.row.image_status = "placeholder"  # slow tiers + t2i exhausted -> terminal
                stats.exhausted += 1
        db.commit()

    # --- Pass 3: SOURCELESS residue (no email) — feed/search only, if enabled ----
    if sourceless and (settings.GMAIL_FEED_ENABLED or settings.GMAIL_SEARCH_ENABLED):
        for t in sourceless:
            if fetch_budget.remaining <= 0:
                stats.budget_stopped = True
                break
            resolved = resolve_item_images(
                payload={},
                items=[_resolver_item(t)],
                client=http,
                token=token,
                msg_id="",
                storage_client=storage_client,
                cache=cache,
                user_id=user_id,
                verify_budget=verify_budget,
                fetch_budget=fetch_budget,
                search_budget=search_budget,
                tiers=_SOURCELESS_TIERS,
                usage=usage,
                gen_budget=gen_budget,
            )
            r = resolved[0]
            if r.stored_url:
                t.row.image_url = r.stored_url
                t.row.image_status = "resolved"
                if r.person and hasattr(t.row, "person_status"):
                    t.row.person_status = r.person
                    stats.person_checked += 1
                if r.tier == "generated":
                    # A generated card passed the verify-v2 invariant gates by construction.
                    if hasattr(t.row, "invariant_checked_at"):
                        t.row.invariant_checked_at = _now_utc()
                    stats.generated += 1
                else:
                    stats.slow_filled += 1
                stats.tier_counts[r.tier] += 1
                db.commit()
                continue
            # No source image at all -> t2i from attributes before a placeholder.
            gen_url = _maybe_t2i(t, storage_client, user_id, gen_budget, verify_budget, usage)
            if gen_url:
                t.row.image_url = gen_url
                t.row.image_status = "resolved"
                if hasattr(t.row, "person_status"):
                    t.row.person_status = "person_free"  # t2i is person-free by construction
                    stats.person_checked += 1
                if hasattr(t.row, "invariant_checked_at"):
                    t.row.invariant_checked_at = _now_utc()
                stats.generated += 1
                stats.tier_counts["generated"] += 1
            else:
                t.row.image_status = "placeholder"
                stats.exhausted += 1
            db.commit()
    # else: sourceless + feed/search disabled -> nothing left to try; leave 'pending'
    # so a future cache seed fills it cheaply on the next self-heal run.


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_image_fill(
    user_id: UUID,
    db,
    *,
    sync_id: Optional[UUID] = None,
    include_candidates: bool = True,
    include_confirmed: bool = True,
    candidate_limit: Optional[int] = None,
    confirmed_limit: Optional[int] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> ImageFillStats:
    """Background image fill + self-heal for ONE user. Never raises (background tail).

    ``sync_id``, when given, attributes the vision-verify + Serper usage this pass
    incurs to that ingest_run (cost tracking); standalone self-heal passes leave it
    None and simply don't persist cost.

    Targets, in order:
      * still-imageless swipe candidates (status='pending', image_url null, image_status
        pending/null) — this is the streaming fill behind the live deck.
      * pending confirmed clothing_items (image_status='pending', image_url null) — the
        self-heal pass; cache-first so shared-catalog hits cost ~0.

    Idempotent and budget-capped (shared Verify/Fetch/Search budgets). Both groups share
    one HTTP client, one fetched-once cache, and one budget set, so the whole pass is
    bounded regardless of how the work splits across candidates vs confirmed items.
    """
    t0 = time.time()
    stats = ImageFillStats(user_id=user_id)

    try:
        cand_rows: List[IngestCandidate] = []
        if include_candidates:
            # Ready-first Phase 2: selection is STATE-driven, not image-driven. Every
            # pending GMAIL candidate that hasn't reached a terminal state is work:
            # imageless ones need the resolver/generation ladder; image-bearing ones
            # with person_status='unknown' need the affirmative person check (the
            # Break-A backlog). Photo candidates are NEVER selected here — the photo
            # generation service owns their state machine.
            cand_rows = (
                db.query(IngestCandidate)
                .filter(
                    IngestCandidate.user_id == user_id,
                    IngestCandidate.status == "pending",
                    IngestCandidate.source_type == "gmail",
                    IngestCandidate.pipeline_state.notin_(_TERMINAL_STATES),
                    # Gate-1 locked policy: a needs_enrichment row is a REAL purchase
                    # whose email carried only variant text ("Black-L") — admitted to
                    # the closet pipeline but EXCLUDED from image generation until the
                    # enrichment join (or the user) supplies a product name.
                    IngestCandidate.needs_enrichment.is_(False),
                )
                .order_by(IngestCandidate.created_at.asc())
                .limit(candidate_limit or settings.GMAIL_IMAGE_FILL_MAX_CANDIDATES)
                .all()
            )
        confirmed_rows: List[ClothingItem] = []
        if include_confirmed:
            confirmed_rows = (
                db.query(ClothingItem)
                .filter(
                    ClothingItem.user_id == user_id,
                    ClothingItem.image_status == "pending",
                    ClothingItem.image_url.is_(None),
                )
                .order_by(ClothingItem.created_at.desc())
                .limit(confirmed_limit or settings.GMAIL_SELF_HEAL_MAX_ITEMS)
                .all()
            )

        stats.candidates_seen = len(cand_rows)
        stats.confirmed_seen = len(confirmed_rows)
        if not cand_rows and not confirmed_rows:
            stats.elapsed = time.time() - t0
            return stats

        # Gmail token (for the slow email re-fetch) — optional. Without it (or without
        # storage) only the cache-first pass runs; the residue stays 'pending'.
        token: Optional[str] = None
        account = (
            db.query(GoogleAccount).filter(GoogleAccount.user_id == user_id).first()
        )
        if account and account.refresh_token:
            try:
                token = ensure_fresh_token(account, db)
            except Exception:
                logger.warning("image_fill user=%s: token refresh failed; cache-only", user_id)

        storage_client = None
        try:
            from app.utils.supabase_storage import SupabaseStorageClient

            storage_client = SupabaseStorageClient.from_env()
        except Exception:
            logger.info("image_fill user=%s: storage not configured; cache-only", user_id)

        cache = ResolvedImageCache()
        verify_budget = VerifyBudget(settings.GMAIL_VERIFY_MAX_PER_RUN)
        fetch_budget = FetchBudget(settings.GMAIL_FETCH_MAX_PER_RUN)
        search_budget = SearchBudget(settings.GMAIL_SEARCH_MAX_PER_RUN)
        # Wave B (Fix 4): caps generations this pass (on-model routing + t2i fallback),
        # shared across all targets. Generation is background-only — this budget is what
        # enables it here (blocking extraction never constructs one), so the deck is never
        # delayed by a generation call.
        gen_budget = GenerationBudget(settings.GENERATION_MAX_PER_RUN)
        # Records the REAL vision-verify tokens + Serper credits this pass spends, for
        # per-sync cost attribution (persisted below when a sync_id is given).
        usage = UsageAccumulator()

        # --- Ready-first Phase 2, step 1: canonicalize-lite --------------------------
        # Default missing sizes from the user's onboarding facts (the same lookup the
        # confirm path uses) and advance staged -> canonicalized. One facts load per run.
        facts = load_user_facts(db, user_id)
        for c in cand_rows:
            _apply_canonicalized(c, facts)
        db.commit()

        # Image work targets: only the IMAGELESS candidates go through the resolver
        # waterfall; image-bearing candidates with an unknown person status go through
        # the person-reconcile pass below instead. Confirmed-item self-heal unchanged.
        imageless = [c for c in cand_rows if not c.image_url]
        for c in imageless:
            _advance(c, "image_pending")
        db.commit()

        targets = (
            [_candidate_target(c) for c in imageless]
            + [_clothing_target(it) for it in confirmed_rows]
        )

        # The client serves BOTH the slow email tiers (needs token) and the person-
        # reconcile fetches of already-stored images (no token needed) — build it
        # whenever either kind of work exists.
        client_cm = httpx.Client(
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=10)
        )
        try:
            http = client_cm
            _resolve_targets(
                db, targets,
                user_id=user_id, token=token, http=http, storage_client=storage_client,
                cache=cache, verify_budget=verify_budget, fetch_budget=fetch_budget,
                search_budget=search_budget, usage=usage, stats=stats,
                should_cancel=should_cancel, gen_budget=gen_budget,
            )

            # --- Ready-first Phase 2, step 2: affirmative person check ---------------
            # Every gmail candidate that now HAS an image but still an 'unknown' person
            # status (the pre-Phase-2 backlog + fresh cache-tier fills, which are not
            # re-verified) gets a verify pass; person images route through generation.
            recon = [
                c for c in cand_rows
                if c.image_url and c.person_status == "unknown"
                and c.pipeline_state not in _TERMINAL_STATES
            ]
            for c in recon:
                _advance(c, "image_pending")
            _reconcile_person(
                db, recon,
                user_id=user_id, http=http, storage_client=storage_client,
                gen_budget=gen_budget, verify_budget=verify_budget,
                fetch_budget=fetch_budget, usage=usage, stats=stats,
                should_cancel=should_cancel,
            )
        finally:
            client_cm.close()

        # --- Ready-first Phase 2, step 3: terminal stamping -----------------------
        # Drive every selected gmail candidate to ready / failed / masked-residue.
        # mark_candidate_ready (inside) enforces the invariant: ready ⟺ person_free +
        # stored verified image + complete tags.
        for c in cand_rows:
            _stamp_final(c, stats)
        db.commit()

        # Attribute this pass's verify + search cost to the sync (best-effort).
        record_fill_usage(db, sync_id, usage)

        stats.elapsed = time.time() - t0
        logger.info(
            "image_fill user=%s: candidates=%d confirmed=%d -> cache=%d slow=%d gen=%d "
            "exhausted=%d fetch_err=%d person_checked=%d person_routed=%d ready=%d "
            "failed=%d budget_stopped=%s elapsed=%.1fs",
            user_id, stats.candidates_seen, stats.confirmed_seen, stats.cache_filled,
            stats.slow_filled, stats.generated, stats.exhausted, stats.fetch_errors,
            stats.person_checked, stats.person_routed, stats.ready, stats.failed,
            stats.budget_stopped, stats.elapsed,
        )
        return stats

    except Exception as exc:  # background tail must never crash the caller
        logger.error("image_fill user=%s: error %s: %s", user_id, type(exc).__name__, exc)
        try:
            db.rollback()
        except Exception:
            pass
        stats.elapsed = time.time() - t0
        return stats
