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
from app.gmail_closet.reconcile import (
    REASON_MERGED,
    LineDecision,
    MessageDecision,
    parse_variant,
    plan_name_merges,
    reconcile_message,
    signatures_match,
)
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
    admitted: int               # reconcile: lines admitted as owned purchases
    demoted: int                # reconcile: lines demoted (rejected_recommendation)
    quarantined: int            # reconcile: emails quarantined for re-extraction
    enriched: int               # variant rows bound to their named confirm line
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
            # --- Reconcile-aware merge (0040) --------------------------------
            # provenance: first evidence wins; a later email only fills a gap.
            "provenance": func.coalesce(c.provenance, ex.provenance),
            # A row is enriched the moment EITHER contributing email carried the
            # real product name.
            "needs_enrichment": c.needs_enrichment & ex.needs_enrichment,
            # Once returned, stays returned (a later re-seen confirm can't unreturn).
            "is_return": c.is_return | ex.is_return,
            # pipeline_state transitions on merge, in precedence order:
            #  1. RETARGETING fingerprint — the same ORDERLESS key re-seen at a
            #     DIFFERENT price is an ad impression stream, never a purchase.
            #     Only early states demote; a verified/ready row is left alone.
            #  2. REVIVAL — new ORDER EVIDENCE admits a previously demoted row
            #     (false negatives are the failure mode to avoid; ties go to admit).
            #  3. otherwise keep the existing state (insert-only semantics).
            "pipeline_state": case(
                (
                    c.order_id.is_(None) & ex.order_id.is_(None)
                    & c.unit_price.isnot(None) & ex.unit_price.isnot(None)
                    & (c.unit_price != ex.unit_price)
                    & c.pipeline_state.in_(("staged", "canonicalized", "image_pending")),
                    "rejected_recommendation",
                ),
                (
                    # Revival: an ADMITTED line (reconcile already verified its order
                    # evidence — the v2 key embeds order_id, so an orderless demoted
                    # row can only collide with another orderless line, admitted via
                    # the totals-reconcile path) beats a previous demotion.
                    (c.pipeline_state == "rejected_recommendation")
                    & (ex.pipeline_state == "staged"),
                    "staged",
                ),
                else_=c.pipeline_state,
            ),
            "quarantine_reason": case(
                (
                    c.order_id.is_(None) & ex.order_id.is_(None)
                    & c.unit_price.isnot(None) & ex.unit_price.isnot(None)
                    & (c.unit_price != ex.unit_price)
                    & c.pipeline_state.in_(("staged", "canonicalized", "image_pending")),
                    "retargeting_multi_price",
                ),
                (
                    (c.pipeline_state == "rejected_recommendation")
                    & (ex.pipeline_state == "staged"),
                    None,
                ),
                (
                    c.pipeline_state == "rejected_recommendation",
                    func.coalesce(c.quarantine_reason, ex.quarantine_reason),
                ),
                else_=c.quarantine_reason,
            ),
        },
    )
    db.execute(stmt)


def _stage_message(
    db,
    *,
    user_id: UUID,
    sync_id: UUID,
    res: _MsgExtraction,
) -> tuple:
    """Stage one message via reconcile: admitted AND demoted lines both persist.

    Stage 1 (extractor) reported the email's STRUCTURE as a ReceiptDocument; the
    deterministic reconcile pass routes every line: admitted lines stage at
    pipeline_state='staged' (the readiness machine's entry), demoted lines stage at
    the TERMINAL 'rejected_recommendation' with a machine-readable quarantine_reason
    (demote-never-delete), and a quarantined email stages NOTHING — the caller marks
    its processed_messages row 'quarantined' for re-extraction. Candidates stage as
    TEXT ONLY (image work is the background fill's). Idempotency is the v2 content-
    key upsert. Returns (decision, admitted_keys, demoted_keys).
    """
    doc = res.outcome.receipt if res.outcome else None

    # CLOTHING GATE: non-clothing emails stage NOTHING. Layer D (is_purchase) was
    # deliberately STRIPPED at merge: reconcile is the single admit/demote gate.
    if not doc or not doc.is_clothing:
        return None, [], []
    if not (doc.order_lines or doc.recommendation_lines or doc.returned_lines):
        return None, [], []

    decision = reconcile_message(res.message_id, doc)
    if decision.quarantined:
        return decision, [], []

    order = doc.order
    order_date = normalize_order_date(order.order_date if order else None)
    currency = normalize_currency(order.currency if order else None)
    # Known-retailer prior fills merchant/brand when the model left them null.
    merchant = doc.merchant or res.retailer

    admitted_keys: list = []
    demoted_keys: list = []
    for ld in decision.admitted + decision.demoted:
        line = ld.line
        fields = line.confidence.model_dump() if line.confidence else {}
        present = [v for v in fields.values() if isinstance(v, (int, float))]
        item_overall = (sum(present) / len(present)) if present else doc.overall_confidence
        brand = line.brand or res.retailer  # strong brand prior for known retailers

        _upsert_candidate(
            db,
            dict(
                user_id=user_id,
                sync_id=sync_id,
                message_id=res.message_id,
                source_line_key=ld.content_key,
                source_message_ids=[res.message_id],
                seen_count=1,
                name=line.name,
                brand=brand,
                category=line.category.value if line.category else None,
                color=line.color,
                size=line.size,
                quantity=line.qty or 1,
                unit_price=line.unit_price,
                currency=currency,
                order_date=order_date,
                is_return=ld.is_return,
                merchant=merchant,
                order_id=decision.order_id,
                image_url=None,
                image_status="pending",
                confidence_overall=item_overall,
                confidence_json={
                    "fields": fields,
                    "receipt_overall": doc.overall_confidence,
                    "model": res.outcome.model,
                    "escalated": res.outcome.escalated,
                },
                status="pending",
                # Admitted lines enter the readiness machine at 'staged' (unknown
                # person status — fail-closed, masked, never deck-visible until
                # 'ready'). Demoted lines are born TERMINAL at
                # 'rejected_recommendation' with their reason — kept for audit,
                # invisible to deck/settle/fill/confirm via the terminal allowlists.
                pipeline_state="staged" if ld.admitted else "rejected_recommendation",
                quarantine_reason=ld.reason,
                needs_enrichment=ld.needs_enrichment,
                provenance=ld.provenance,
                person_status="unknown",
            ),
        )
        (admitted_keys if ld.admitted else demoted_keys).append(ld.content_key)

    return decision, admitted_keys, demoted_keys


def _mark_extracted(
    db, user_id: UUID, message_id: str,
    *, email_kind: Optional[str] = None, quarantined: bool = False,
) -> None:
    """Flip processed_messages.status 'fetched' -> 'extracted' (or 'quarantined')
    and persist the Stage-1 email_kind verdict (0040)."""
    values = {
        "status": "quarantined" if quarantined else "extracted",
        "processed_at": datetime.now(timezone.utc),
    }
    if email_kind is not None:
        values["email_kind"] = email_kind
    db.query(ProcessedMessage).filter(
        ProcessedMessage.user_id == user_id,
        ProcessedMessage.message_id == message_id,
    ).update(values, synchronize_session=False)


def _enrichment_pass(db, user_id: UUID, sync_id: UUID) -> int:
    """Bind fulfillment variant rows to their named order-confirmation rows (DB level).

    The in-memory corpus join (reconcile.enrichment_join) covers the reprocess script;
    this is its incremental twin for live syncs, where the confirm and ship emails may
    arrive in DIFFERENT runs: for every order_id touched by THIS run, load the user's
    full candidate set for that order and merge each needs_enrichment variant row into
    the unique named row matching its parsed (color, size) — bidirectionally unique,
    else it stays needs_enrichment. The named row absorbs the variant's source
    message ids; the variant row is demoted terminal with reason 'merged_duplicate'
    (demote-never-delete). Returns #rows merged.
    """
    touched = (
        db.query(IngestCandidate.order_id)
        .filter(
            IngestCandidate.user_id == user_id,
            IngestCandidate.sync_id == sync_id,
            IngestCandidate.source_type == "gmail",
            IngestCandidate.order_id.isnot(None),
        )
        .distinct()
        .all()
    )
    order_ids = [r[0] for r in touched]
    if not order_ids:
        return 0

    merged = 0
    for order_id in order_ids:
        rows = (
            db.query(IngestCandidate)
            .filter(
                IngestCandidate.user_id == user_id,
                IngestCandidate.source_type == "gmail",
                IngestCandidate.order_id == order_id,
                IngestCandidate.pipeline_state != "rejected_recommendation",
            )
            .all()
        )
        named = [r for r in rows if not r.needs_enrichment and not r.is_return]
        variants = [r for r in rows if r.needs_enrichment and not r.is_return]
        if not named or not variants:
            continue

        def _named_sig(r):
            return ((r.color or "").strip().lower() or None,
                    (r.size or "").strip().lower() or None)

        def _var_sig(r):
            vcolor, vsize = parse_variant(r.name)
            if r.color:
                vcolor = r.color.strip().lower() or vcolor
            if r.size:
                vsize = r.size.strip().lower() or vsize
            return vcolor, vsize

        var_matches = {
            r.id: [n for n in named if signatures_match(_named_sig(n), _var_sig(r))]
            for r in variants if _var_sig(r) != (None, None)
        }
        claim_count: dict = {}
        for matches in var_matches.values():
            if len(matches) == 1:
                claim_count[matches[0].id] = claim_count.get(matches[0].id, 0) + 1

        for var in variants:
            matches = var_matches.get(var.id, [])
            if len(matches) != 1 or claim_count.get(matches[0].id, 0) != 1:
                continue
            target = matches[0]
            # Named row absorbs the variant's provenance trail.
            existing = set(target.source_message_ids or [])
            for mid in var.source_message_ids or []:
                if mid not in existing:
                    target.source_message_ids = (target.source_message_ids or []) + [mid]
                    existing.add(mid)
                    target.seen_count = (target.seen_count or 1) + 1
            vcolor, vsize = _var_sig(var)
            target.color = target.color or vcolor
            target.size = target.size or vsize
            # Variant row: demoted terminal, reason recorded — never deleted.
            var.pipeline_state = "rejected_recommendation"
            var.quarantine_reason = REASON_MERGED
            var.needs_enrichment = False
            merged += 1

    if merged:
        db.commit()
    return merged


def _name_drift_pass(db, user_id: UUID, sync_id: UUID) -> int:
    """Collapse same-order name-drift rows in the DB (incremental twin of
    reconcile.merge_order_name_drift): for every order touched by this run, plan
    merges over the order's admitted rows and absorb each source row into its
    canonical (longest-name) row — message ids united, source demoted terminal
    with reason 'merged_duplicate'. Returns #rows merged."""
    touched = (
        db.query(IngestCandidate.order_id)
        .filter(
            IngestCandidate.user_id == user_id,
            IngestCandidate.sync_id == sync_id,
            IngestCandidate.source_type == "gmail",
            IngestCandidate.order_id.isnot(None),
        )
        .distinct()
        .all()
    )
    merged = 0
    for (order_id,) in touched:
        rows = (
            db.query(IngestCandidate)
            .filter(
                IngestCandidate.user_id == user_id,
                IngestCandidate.source_type == "gmail",
                IngestCandidate.order_id == order_id,
                IngestCandidate.pipeline_state != "rejected_recommendation",
                IngestCandidate.is_return.is_(False),
            )
            .all()
        )
        by_key = {r.source_line_key: r for r in rows}
        mapping = plan_name_merges(
            [(r.source_line_key, r.name, r.size, r.color) for r in rows])
        for src_key, dst_key in mapping.items():
            src, dst = by_key[src_key], by_key[dst_key]
            existing = set(dst.source_message_ids or [])
            for mid in src.source_message_ids or []:
                if mid not in existing:
                    dst.source_message_ids = (dst.source_message_ids or []) + [mid]
                    existing.add(mid)
                    dst.seen_count = (dst.seen_count or 1) + 1
            dst.size = dst.size or src.size
            dst.color = dst.color or src.color
            dst.needs_enrichment = bool(dst.needs_enrichment and src.needs_enrichment)
            src.pipeline_state = "rejected_recommendation"
            src.quarantine_reason = REASON_MERGED
            merged += 1
    if merged:
        db.commit()
    return merged


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
        fetch_errors=0, llm_errors=0,
        admitted=0, demoted=0, quarantined=0, enriched=0,
        images_attached=0,
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

                        decision, admitted_keys, demoted_keys = _stage_message(
                            db, user_id=user_id, sync_id=sync_id, res=res)

                        if decision is not None and decision.quarantined:
                            # Invariant alarm: the email is HELD for re-extraction —
                            # never marked done, never silently admitted or dropped.
                            stats.quarantined += 1
                            _mark_extracted(
                                db, user_id, res.message_id,
                                email_kind=decision.email_kind, quarantined=True)
                            continue

                        stats.admitted += len(admitted_keys)
                        stats.demoted += len(demoted_keys)
                        if admitted_keys:
                            stats.clothing_msgs += 1
                            stats.items_extracted += len(admitted_keys)
                            for k in admitted_keys:
                                if k in seen_keys:
                                    stats.merged_duplicates += 1  # collapsed into existing candidate
                                else:
                                    seen_keys.add(k)
                        else:
                            stats.rejected_msgs += 1

                        _mark_extracted(
                            db, user_id, res.message_id,
                            email_kind=decision.email_kind if decision else None)

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
        # Post-run ENRICHMENT PASS: bind this run's fulfillment variant rows to
        # their order-confirmation named lines (same user + order_id), then record
        # the reconcile metrics onto the run row.
        try:
            stats.enriched = _enrichment_pass(db, user_id, sync_id)
            stats.enriched += _name_drift_pass(db, user_id, sync_id)
        except Exception:
            logger.warning("sync_id=%s: enrichment pass failed (non-fatal)", sync_id)

        if run:
            run.status = "completed"
            run.extracted_count = stats.candidates_staged
            run.admitted_count = stats.admitted
            run.demoted_count = stats.demoted
            run.quarantined_count = stats.quarantined
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
