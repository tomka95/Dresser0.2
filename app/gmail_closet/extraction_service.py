"""Phase 3c extraction pass: Tier-1-kept emails -> staged CLOTHING candidates.

Where 3b ends, this begins. 3b fetched every matching message, ran the Tier-1
filter, and wrote a row to processed_messages with status 'fetched' (kept) or
'filtered_out' (dropped). This pass picks up exactly the status='fetched' rows,
re-fetches each body from Gmail, runs the LLM extractor, applies the CLOTHING
GATE, and stages only clothing items into ingest_candidates.

WHY A SEPARATE PASS (not folded into fetch): the 3b fetch/filter/token seam is
left UNCHANGED. Extraction keys off processed_messages.status, so it is naturally
idempotent — a message is extracted exactly once (status flips 'fetched' ->
'extracted'); a re-run finds nothing left to do.

DB write path mirrors 3b: SQLAlchemy via the owner-role connection (RLS bypassed
by the role, user_id pinned SERVER-SIDE). The SQLAlchemy Session is NOT shared
with worker threads — threads only do network + LLM work and return plain data;
ALL DB writes happen on the calling thread.

NOTHING here writes to clothing_items (that is phase 3d, confirm). Subjects and
bodies are NEVER logged — only message_id, counts, and token counts.
"""
from __future__ import annotations

import logging
import time
import uuid as _uuid_mod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional
from uuid import UUID

import httpx
from sqlalchemy import case, func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.gmail_closet.extraction_schema import (
    make_content_key,
    normalize_currency,
    normalize_order_date,
)
from app.gmail_closet.email_type_classifier import classify_is_order_confirmation
from app.gmail_closet.extractor import ExtractionOutcome, extract_receipt
from app.gmail_closet.fetch_service import (
    _extract_body,
    _fetch_one,
)
from app.gmail_closet.gmail_oauth_service import ensure_fresh_token
from app.gmail_closet.receipt_filter import is_ambiguous_type
from app.gmail_closet.retailers import match_retailer
from app.platform.usage import record_extraction_usage
from app.models import GoogleAccount, IngestCandidate, IngestRun, ProcessedMessage

logger = logging.getLogger(__name__)

_MAX_CONCURRENT = max(1, settings.GMAIL_EXTRACT_MAX_CONCURRENCY)
_BATCH_SIZE = 50
# Commit staged candidates this often WITHIN a batch (not just at batch end) so the
# progressive deck can stream cards in within a couple of LLM round-trips instead of
# waiting for a whole 50-message batch — this is what makes the first swipeable card
# appear in seconds. Each commit is tiny (a few upserts); the cadence bounds overhead.
_COMMIT_EVERY = 8


# ---------------------------------------------------------------------------
# Public return type
# ---------------------------------------------------------------------------

@dataclass
class ExtractionStats:
    """Summary returned by run_extraction_sync. All counts are redaction-safe."""
    sync_id: UUID
    status: str                 # 'completed' | 'error'
    emails_to_llm: int          # status='fetched' messages sent to the extractor
    items_extracted: int        # total clothing line items seen across emails
    candidates_staged: int      # DISTINCT candidates after content-key dedup
    merged_duplicates: int      # line items collapsed into an existing candidate
    clothing_msgs: int          # emails that passed the clothing gate (>=1 item)
    rejected_msgs: int          # emails gated out as non-clothing
    escalated: int              # emails that fell through to the stronger model
    parse_failures: int         # emails where a REAL model response failed to parse
    fetch_errors: int           # messages we could not re-fetch (404 / max retries)
    llm_errors: int             # LLM call never completed (5xx/429 after retries);
                                # left status='fetched' for a later sync to retry
    images_attached: int        # candidates that got an image_url (any tier)
    images_inline: int          # ... resolved via an inline (cid) image part
    images_email_img: int       # ... resolved via an embedded remote product-image URL
    images_og: int              # ... resolved via a product-link og:image
    input_tokens: int
    output_tokens: int
    est_cost_flash_lite: float  # all tokens at Flash-Lite rate (headline)
    est_cost_realistic: float   # at the rate(s) actually used (incl. escalations)
    elapsed: float


# ---------------------------------------------------------------------------
# Internal per-message result (produced in worker threads, no DB touched)
# ---------------------------------------------------------------------------

@dataclass
class _MsgExtraction:
    message_id: str
    outcome: Optional[ExtractionOutcome]   # None on unrecoverable fetch error
    sent_at: Optional[datetime]
    # Known-retailer display name resolved from the sender domain (retailers.py),
    # used as a strong brand/merchant prior when the model leaves them null.
    retailer: Optional[str] = None
    # Layer C: the cheap TYPE classifier judged this ambiguous email marketing/abandoned-
    # cart (not an order confirmation), so it was dropped BEFORE the full extraction call.
    # Distinct from outcome=None (a fetch error to retry): a type-reject is DONE — the
    # service marks it 'extracted' and never re-runs it.
    type_rejected: bool = False


# ---------------------------------------------------------------------------
# Worker: re-fetch + extract one message (NO DB access)
# ---------------------------------------------------------------------------

def _parse_headers(payload: dict) -> tuple[str, str]:
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    return headers.get("from", ""), headers.get("subject", "")


def _internal_date(raw: dict) -> Optional[datetime]:
    """Gmail internalDate is epoch milliseconds (string). Best-effort -> UTC datetime."""
    ms = raw.get("internalDate")
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return None


def _count_inline_image_parts(payload: dict) -> int:
    """Count image/* parts (data or attachment) WITHOUT fetching bytes — a cheap
    prior for the extractor. The real per-item image fetch happens later, off the
    blocking path, in the background image-fill worker (image_fill_service)."""
    n = 0

    def _walk(node: dict) -> None:
        nonlocal n
        if (node.get("mimeType", "") or "").lower().startswith("image/"):
            body = node.get("body", {}) or {}
            if body.get("data") or body.get("attachmentId"):
                n += 1
        for part in node.get("parts", []) or []:
            _walk(part)

    _walk(payload)
    return n


def _fetch_and_extract(
    client: httpx.Client,
    token: str,
    msg_id: str,
) -> _MsgExtraction:
    """Re-fetch one kept message and run the LLM extractor. NO image work, NO DB access.

    Phase-A image change: ALL image resolution (fast AND slow tiers) is pulled OUT of
    this blocking extraction path and into the background image-fill worker, so a
    candidate is staged as a TEXT card the instant the LLM returns — never waiting on a
    guarded fetch or a vision-verify call. Each worker now makes exactly ONE Gemini
    extraction call (plus an escalation only for low-confidence clothing), which is what
    lets the first swipeable card appear within seconds instead of at second ~110.
    """
    raw = _fetch_one(client, token, msg_id)
    if raw is None:
        return _MsgExtraction(message_id=msg_id, outcome=None, sent_at=None)

    payload = raw.get("payload", {})
    sender, subject = _parse_headers(payload)
    body = _extract_body(payload)
    sent_at = _internal_date(raw)
    retailer = match_retailer(sender)  # known-retailer brand/merchant prior
    labels = raw.get("labelIds", [])   # Gmail category (top-level field)

    # Layer C: for the AMBIGUOUS residue only (known retailer + order-ish subject + price
    # but no order number, e.g. "Your order is waiting"), ask the cheap TYPE classifier
    # BEFORE the full extraction. A marketing/abandoned-cart verdict drops the email
    # without paying for extraction; fail-open keeps it (never drops a genuine receipt).
    if is_ambiguous_type(sender, subject, body, labels):
        snippet = raw.get("snippet", "")
        if not classify_is_order_confirmation(sender, subject, snippet):
            return _MsgExtraction(
                message_id=msg_id, outcome=None, sent_at=sent_at,
                retailer=retailer, type_rejected=True,
            )

    outcome = extract_receipt(
        sender=sender,
        subject=subject,
        sent_at=sent_at.isoformat() if sent_at else None,
        body=body,
        inline_image_count=_count_inline_image_parts(payload),
    )

    return _MsgExtraction(
        message_id=msg_id, outcome=outcome, sent_at=sent_at, retailer=retailer
    )


# ---------------------------------------------------------------------------
# Staging (calling thread only)
# ---------------------------------------------------------------------------

def _upsert_candidate(db, vals: dict) -> None:
    """INSERT one candidate, or ON CONFLICT merge it into the existing one.

    Conflict target is UNIQUE(user_id, source_line_key) — the content key — so the
    same owned item arriving in a second email (order vs shipping confirmation)
    UPDATEs the existing row instead of inserting a duplicate. The merge is
    fill-nulls / keep-richest: scalar fields COALESCE existing-then-incoming (so
    order_id / order_date populate as soon as any contributing email carries them),
    confidence keeps the max, a non-'other' category upgrades a prior 'other', and
    the contributing message is appended to source_message_ids (seen_count counts
    distinct source emails). Name/quantity/is_return/confidence_json keep the
    first-seen values.
    """
    tbl = IngestCandidate.__table__
    stmt = pg_insert(tbl).values(**vals)
    ex = stmt.excluded
    c = tbl.c
    # EXCLUDED.source_message_ids is the single-element [message_id] of this insert.
    already = c.source_message_ids.op("@>")(ex.source_message_ids)
    stmt = stmt.on_conflict_do_update(
        constraint="ingest_candidates_user_id_source_line_key_key",
        set_={
            "brand": func.coalesce(c.brand, ex.brand),
            "merchant": func.coalesce(c.merchant, ex.merchant),
            "order_id": func.coalesce(c.order_id, ex.order_id),
            "order_date": func.coalesce(c.order_date, ex.order_date),
            "image_url": func.coalesce(c.image_url, ex.image_url),
            # Keep image_status in lock-step with the merged image_url: if EITHER email
            # contributed an image the candidate is 'resolved', else keep the existing
            # status (a 'placeholder' from an earlier exhausted fill must not regress).
            "image_status": case(
                (func.coalesce(c.image_url, ex.image_url).isnot(None), "resolved"),
                else_=c.image_status,
            ),
            "color": func.coalesce(c.color, ex.color),
            "size": func.coalesce(c.size, ex.size),
            "currency": func.coalesce(c.currency, ex.currency),
            "unit_price": func.coalesce(c.unit_price, ex.unit_price),
            "category": case(
                (c.category == "other", func.coalesce(ex.category, c.category)),
                else_=c.category,
            ),
            "confidence_overall": func.greatest(c.confidence_overall, ex.confidence_overall),
            "source_message_ids": case(
                (already, c.source_message_ids),
                else_=c.source_message_ids.op("||")(ex.source_message_ids),
            ),
            "seen_count": c.seen_count + case((already, 0), else_=1),
        },
    )
    db.execute(stmt)


def _stage_message(
    db,
    *,
    user_id: UUID,
    sync_id: UUID,
    res: _MsgExtraction,
) -> list:
    """Stage one message's clothing items via content-key upsert; return content keys.

    The content key per staged line lets the caller count DISTINCT vs merged candidates
    at run level. The CLOTHING GATE is applied first — non-clothing (or itemless) emails
    stage NOTHING. Candidates are staged as TEXT ONLY with image_url=NULL and
    image_status='pending': all image resolution now happens in the background fill, so
    the card is swipeable the instant it's staged (no image work blocks staging).
    Idempotency is the content-key upsert itself.
    """
    receipt = res.outcome.receipt if res.outcome else None

    # PURCHASE-TYPE GATE (Layer D) + CLOTHING GATE: stage NOTHING unless this is a genuine
    # purchase (is_purchase) that contains wearable clothing (is_clothing) with items.
    # is_purchase was already in the schema but never consulted — gating on it here is the
    # LLM backstop: a promotional / abandoned-cart email that names a garment + price and
    # slips past the earlier layers still stages nothing once the model marks is_purchase=false.
    if not receipt or not receipt.is_purchase or not receipt.is_clothing or not receipt.items:
        return []

    order_date = normalize_order_date(receipt.order_date)
    currency = normalize_currency(receipt.currency)
    # Known-retailer prior fills merchant/brand when the model left them null.
    merchant = receipt.merchant or res.retailer

    content_keys: list = []
    for item in receipt.items:
        fields = item.confidence.model_dump() if item.confidence else {}
        present = [v for v in fields.values() if isinstance(v, (int, float))]
        item_overall = (sum(present) / len(present)) if present else receipt.overall_confidence

        content_key = make_content_key(item.name, item.size, item.color, item.unit_price)
        brand = item.brand or res.retailer  # strong brand prior for known retailers

        # Text-only stage: no image yet. The background fill resolves every tier and
        # flips image_status 'pending' -> 'resolved' (or 'placeholder' when exhausted).
        image_url = None
        image_status = "pending"

        _upsert_candidate(
            db,
            dict(
                user_id=user_id,
                sync_id=sync_id,
                message_id=res.message_id,
                source_line_key=content_key,
                source_message_ids=[res.message_id],
                seen_count=1,
                name=item.name,
                brand=brand,
                category=item.category.value if item.category else None,
                color=item.color,
                size=item.size,
                quantity=item.qty or 1,
                unit_price=item.unit_price,
                currency=currency,
                order_date=order_date,
                is_return=bool(item.is_return),
                merchant=merchant,
                order_id=receipt.order_id,
                image_url=image_url,
                image_status=image_status,
                confidence_overall=item_overall,
                confidence_json={
                    "fields": fields,
                    "receipt_overall": receipt.overall_confidence,
                    "model": res.outcome.model,
                    "escalated": res.outcome.escalated,
                },
                status="pending",
                # Ready-first Phase 1: Gmail candidates enter the readiness machine at
                # 'staged' with an UNKNOWN person status (no detector has run — fail-
                # closed, masked). Phase 2 (email verify+generation) advances them to
                # 'ready'; until then they never reach the ready-gated deck. Insert-only:
                # the ON CONFLICT set_ below never touches either, so a re-seen email
                # can't regress a candidate that later phases advanced.
                pipeline_state="staged",
                person_status="unknown",
            ),
        )
        content_keys.append(content_key)

    return content_keys


def _mark_extracted(db, user_id: UUID, message_id: str) -> None:
    """Flip processed_messages.status 'fetched' -> 'extracted' for this message."""
    db.query(ProcessedMessage).filter(
        ProcessedMessage.user_id == user_id,
        ProcessedMessage.message_id == message_id,
    ).update(
        {"status": "extracted", "processed_at": datetime.now(timezone.utc)},
        synchronize_session=False,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_extraction_sync(
    user_id: UUID,
    db,
    sync_id: Optional[UUID] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> ExtractionStats:
    """Run one extraction pass for a user. Creates its own IngestRun (extraction run).

    Picks up every processed_messages row with status='fetched', re-fetches the
    body, extracts, gates on clothing, stages candidates, and flips the status to
    'extracted'. ingest_runs.extracted_count is set to the number of staged
    candidates. Idempotent: re-running finds no status='fetched' rows left.

    ``should_cancel``: checked at each extraction-batch boundary. On cancel the
    loop stops promptly, the run is left 'running' (never finalized 'completed'),
    and status='cancelled' is returned. Already-extracted messages are committed
    incrementally and flipped to 'extracted', so a resumed run re-extracts only
    what's left. Default None -> never cancels (legacy path unaffected).
    """
    t0 = time.time()

    account = (
        db.query(GoogleAccount)
        .filter(GoogleAccount.user_id == user_id)
        .first()
    )
    if not account or not account.refresh_token:
        raise ValueError(f"No Gmail connection for user {user_id}. Connect via /gmail/oauth/start.")

    if sync_id is None:
        sync_id = _uuid_mod.uuid4()
        run = IngestRun(sync_id=sync_id, user_id=user_id, status="running")
        db.add(run)
        db.commit()
    run = db.query(IngestRun).filter(IngestRun.sync_id == sync_id).first()

    # The kept-but-not-yet-extracted work list. Ordered CLOTHING-LIKELY FIRST
    # (extract_priority ascending) so probable-clothing emails hit the LLM first and the
    # first swipeable card stages in the opening seconds, not at the end of the run.
    # priority was computed cheaply at fetch time (known retailer / clothing subject).
    rows = (
        db.query(ProcessedMessage.message_id)
        .filter(
            ProcessedMessage.user_id == user_id,
            ProcessedMessage.status == "fetched",
        )
        .order_by(
            ProcessedMessage.extract_priority.asc(),  # clothing-likely (0) before other (1)
            ProcessedMessage.processed_at.asc(),       # stable FIFO within a priority
        )
        .all()
    )
    message_ids = [r[0] for r in rows]
    logger.info("sync_id=%s: extraction over %d kept message(s)", sync_id, len(message_ids))

    stats = ExtractionStats(
        sync_id=sync_id, status="completed",
        emails_to_llm=0, items_extracted=0, candidates_staged=0, merged_duplicates=0,
        clothing_msgs=0, rejected_msgs=0, escalated=0, parse_failures=0,
        fetch_errors=0, llm_errors=0, images_attached=0,
        images_inline=0, images_email_img=0, images_og=0,
        input_tokens=0, output_tokens=0,
        est_cost_flash_lite=0.0, est_cost_realistic=0.0, elapsed=0.0,
    )

    if not message_ids:
        if run:
            run.status = "completed"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
        stats.elapsed = time.time() - t0
        return stats

    try:
        access_token = ensure_fresh_token(account, db)
    except Exception:
        logger.error("sync_id=%s: token refresh failed", sync_id)
        if run:
            run.status = "error"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
        stats.status = "error"
        stats.elapsed = time.time() - t0
        return stats

    # Run-level content keys, so DISTINCT-vs-merged counting reflects dedup ACROSS
    # batches (the DB ON CONFLICT enforces it; this set just reports it).
    seen_keys: set = set()

    try:
        with httpx.Client(
            limits=httpx.Limits(
                max_connections=_MAX_CONCURRENT + 10,
                max_keepalive_connections=_MAX_CONCURRENT,
            )
        ) as http:
            cancelled = False
            for batch_start in range(0, len(message_ids), _BATCH_SIZE):
                if should_cancel is not None and should_cancel():
                    logger.info(
                        "sync_id=%s: cancellation requested — stopping extraction at %d/%d",
                        sync_id, batch_start, len(message_ids),
                    )
                    cancelled = True
                    break
                batch = message_ids[batch_start : batch_start + _BATCH_SIZE]
                n_workers = min(_MAX_CONCURRENT, len(batch))

                # Stage + commit AS each worker completes (calling thread only — workers
                # never touch the DB), so candidates become queryable within a couple of
                # LLM round-trips and the progressive deck streams them in immediately.
                with ThreadPoolExecutor(max_workers=n_workers) as pool:
                    futures = {
                        pool.submit(_fetch_and_extract, http, access_token, mid): mid
                        for mid in batch
                    }
                    since_commit = 0
                    for future in as_completed(futures):
                        mid = futures[future]
                        try:
                            res = future.result()
                        except Exception:
                            stats.fetch_errors += 1
                            logger.warning(
                                "sync_id=%s message_id=%s: extract worker error", sync_id, mid,
                            )
                            continue

                        if res.type_rejected:
                            # Layer C dropped this ambiguous email as marketing/abandoned-cart
                            # BEFORE any extraction call — it's DONE (no LLM spend). Count it
                            # rejected and mark extracted; the batch-end commit persists it.
                            stats.rejected_msgs += 1
                            _mark_extracted(db, user_id, res.message_id)
                            continue

                        if res.outcome is None:
                            # Unrecoverable re-fetch failure — leave status='fetched' so a
                            # later run retries; do not mark extracted.
                            stats.fetch_errors += 1
                            continue
                        if res.outcome.api_failed:
                            # The Gemini call never completed (5xx/429/network after
                            # retries). Leave status='fetched' so a later sync re-attempts
                            # it — do NOT mark extracted and do NOT count it as a parse
                            # failure. Closes the silent-loss gap where a transient outage
                            # would otherwise burn a real receipt.
                            stats.llm_errors += 1
                            continue

                        stats.emails_to_llm += 1
                        stats.input_tokens += res.outcome.input_tokens
                        stats.output_tokens += res.outcome.output_tokens
                        stats.est_cost_flash_lite += res.outcome.est_cost_flash_lite
                        stats.est_cost_realistic += res.outcome.est_cost_realistic
                        if res.outcome.escalated:
                            stats.escalated += 1
                        if res.outcome.parse_failed:
                            stats.parse_failures += 1

                        keys = _stage_message(db, user_id=user_id, sync_id=sync_id, res=res)
                        if keys:
                            stats.clothing_msgs += 1
                            stats.items_extracted += len(keys)
                            for k in keys:
                                if k in seen_keys:
                                    stats.merged_duplicates += 1  # collapsed into existing candidate
                                else:
                                    seen_keys.add(k)
                        else:
                            stats.rejected_msgs += 1

                        _mark_extracted(db, user_id, res.message_id)

                        # Incremental commit so the freshly-staged cards stream out fast.
                        since_commit += 1
                        if since_commit >= _COMMIT_EVERY:
                            stats.candidates_staged = len(seen_keys)
                            if run:
                                run.extracted_count = stats.candidates_staged
                            db.commit()
                            since_commit = 0

                # Flush the batch remainder.
                stats.candidates_staged = len(seen_keys)
                if run:
                    run.extracted_count = stats.candidates_staged
                db.commit()

                done = batch_start + len(batch)
                logger.info(
                    "sync_id=%s: %d/%d extracted — staged=%d rejected=%d escalated=%d errors=%d",
                    sync_id, done, len(message_ids),
                    stats.candidates_staged, stats.rejected_msgs, stats.escalated, stats.fetch_errors,
                )

        stats.candidates_staged = len(seen_keys)

        # Cooperative cancel: leave the run 'running' (resumable) and report
        # 'cancelled'. Already-extracted messages were committed + marked
        # 'extracted' per batch, so a resumed run re-extracts only the remainder.
        # Record the partial (real) cost best-effort before returning.
        if cancelled:
            record_extraction_usage(
                db, sync_id,
                input_tokens=stats.input_tokens,
                output_tokens=stats.output_tokens,
                cost_usd=stats.est_cost_realistic,
            )
            stats.status = "cancelled"
            stats.elapsed = time.time() - t0
            return stats

        # Images are no longer resolved during extraction (the background fill owns them),
        # so the images_* stats stay 0 here. The real Gemini extraction COST is recorded
        # onto the run below.
        if run:
            run.status = "completed"
            run.extracted_count = stats.candidates_staged
            run.finished_at = datetime.now(timezone.utc)
            db.commit()

        # Per-sync cost: write the REAL summed extraction token counts + realistic
        # per-model dollar cost onto the ingest_run (best-effort; never breaks the sync).
        record_extraction_usage(
            db, sync_id,
            input_tokens=stats.input_tokens,
            output_tokens=stats.output_tokens,
            cost_usd=stats.est_cost_realistic,
        )

        stats.elapsed = time.time() - t0
        # Redaction: counts only — no bodies/subjects, and no token counts in logs.
        logger.info(
            "sync_id=%s: extraction DONE. emails=%d staged=%d merged=%d rejected=%d "
            "escalated=%d parse_fail=%d fetch_err=%d llm_err=%d elapsed=%.1fs",
            sync_id, stats.emails_to_llm, stats.candidates_staged, stats.merged_duplicates,
            stats.rejected_msgs, stats.escalated, stats.parse_failures, stats.fetch_errors,
            stats.llm_errors, stats.elapsed,
        )
        return stats

    except Exception as exc:
        logger.error("sync_id=%s: extraction error — %s: %s", sync_id, type(exc).__name__, exc)
        try:
            if run:
                run.status = "error"
                run.finished_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass
        stats.status = "error"
        stats.elapsed = time.time() - t0
        return stats
