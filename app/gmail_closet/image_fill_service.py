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
from app.gmail_closet.image_guard import FetchBudget
from app.gmail_closet.image_resolver import (
    ALL_TIERS,
    ResolvedImageCache,
    ResolverItem,
    resolve_item_images,
)
from app.gmail_closet.image_verify import VerifyBudget
from app.gmail_closet.product_image_cache import lookup_verified, make_cache_key
from app.gmail_closet.shopping_search import SearchBudget
from app.platform.usage import UsageAccumulator, record_fill_usage
from app.services.image_generation.base import GenerationBudget
from app.models import ClothingItem, GoogleAccount, IngestCandidate

logger = logging.getLogger(__name__)

# Tiers tried for a SOURCELESS target (a confirmed item with no source email): no DOM
# to read, so inline/email-img/og can't run — only the brand+name+color tiers do.
_SOURCELESS_TIERS = frozenset({"feed", "search"})


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

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
    return out.url if out.outcome == "ready" else None


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
                if r.tier == "generated":
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
                if r.tier == "generated":
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
            cand_rows = (
                db.query(IngestCandidate)
                .filter(
                    IngestCandidate.user_id == user_id,
                    IngestCandidate.status == "pending",
                    IngestCandidate.image_url.is_(None),
                    IngestCandidate.image_status.in_(("pending", None)),
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

        targets = (
            [_candidate_target(c) for c in cand_rows]
            + [_clothing_target(it) for it in confirmed_rows]
        )

        client_cm = (
            httpx.Client(limits=httpx.Limits(max_connections=10, max_keepalive_connections=10))
            if (token and storage_client is not None)
            else None
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
        finally:
            if client_cm is not None:
                client_cm.close()

        # Attribute this pass's verify + search cost to the sync (best-effort).
        record_fill_usage(db, sync_id, usage)

        stats.elapsed = time.time() - t0
        logger.info(
            "image_fill user=%s: candidates=%d confirmed=%d -> cache=%d slow=%d "
            "exhausted=%d fetch_err=%d budget_stopped=%s elapsed=%.1fs",
            user_id, stats.candidates_seen, stats.confirmed_seen, stats.cache_filled,
            stats.slow_filled, stats.exhausted, stats.fetch_errors, stats.budget_stopped,
            stats.elapsed,
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
