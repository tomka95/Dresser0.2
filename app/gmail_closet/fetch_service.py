"""Phase 3b Gmail fetch service: pagination, concurrent fetch, body parse, idempotency.

Public surface:
  run_ingest_sync(user_id, db, sync_id=None) -> IngestStats
      The one callable used by both the HTTP route (via ingest_background) and
      the dev runner script. Creates an IngestRun row if sync_id is not given
      (script path); reuses the pre-created row if sync_id is given (route path).

  ingest_background(user_id_str, sync_id_str)
      Thin wrapper for Starlette BackgroundTask: creates its own DB session and
      calls run_ingest_sync with the sync_id the route already created.

DB write path: SQLAlchemy via Postgres owner-role pooler connection.
RLS is bypassed by the connection role; user_id is pinned SERVER-SIDE.
NO service_role key needed. NO LLM calls. Subjects/bodies NEVER logged.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import time
import uuid as _uuid_mod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, List, NamedTuple, Optional, Set, Tuple
from uuid import UUID

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.gmail_closet.gmail_oauth_client import default_since
from app.gmail_closet.gmail_oauth_service import ensure_fresh_token
from app.gmail_closet.receipt_filter import clothing_priority, passes_tier1_filter
from app.models import GoogleAccount, IngestRun, ProcessedMessage

logger = logging.getLogger(__name__)

_GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
_MAX_CONCURRENT = 50    # concurrent messages.get per mailbox
_BATCH_SIZE = 100       # messages per ThreadPoolExecutor batch
_BACKOFF_CAP = 64       # max backoff sleep (seconds)

_FIELDS_LIST = "nextPageToken,resultSizeEstimate,messages(id)"
# labelIds -> Gmail's own category (CATEGORY_PROMOTIONS / CATEGORY_PURCHASES) so the Tier-1
# filter can gate on email TYPE, not just content. snippet -> the short preview the cheap
# email-TYPE classifier (Layer C) reads for the ambiguous residue (never the full body).
_FIELDS_GET = "id,internalDate,labelIds,snippet,payload"


# ---------------------------------------------------------------------------
# Public return type
# ---------------------------------------------------------------------------

@dataclass
class IngestStats:
    """Summary returned by run_ingest_sync after a completed (or errored) run."""
    sync_id: UUID
    status: str           # 'completed' | 'error'
    total_listed: int     # message IDs returned by Gmail API (post-pagination)
    total_estimate: int   # Gmail resultSizeEstimate (before pagination)
    skipped: int          # already in processed_messages — idempotency skips
    fetched: int          # passed Tier-1 filter (receipt signals)
    filtered: int         # failed Tier-1 filter (marketing/shipping/no signals)
    errors: int           # messages we could not fetch (404, max retries)
    elapsed: float        # wall-clock seconds


# ---------------------------------------------------------------------------
# Internal types
# ---------------------------------------------------------------------------

class _MsgResult(NamedTuple):
    message_id: str
    kept: bool
    content_hash: str
    # Cheap pre-LLM clothing-likeliness rank (0 = likely → extract first, 1 = other),
    # persisted to processed_messages.extract_priority so the extraction phase can order
    # probable-clothing emails to the front of the LLM queue.
    priority: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sleep_backoff(attempt: int) -> None:
    delay = min(2 ** attempt, _BACKOFF_CAP)
    logger.debug("Rate limit backoff %ds (attempt %d)", delay, attempt + 1)
    time.sleep(delay)


def _build_query(since: datetime) -> str:
    """Tier-0 broad Gmail search: purchases + subject keywords + top retailer domains.

    The full 94-domain allow-list check runs in Tier-1 (receipt_filter.py).
    """
    since_date = since.strftime("%Y/%m/%d")
    top_domains = (
        "amazon.com OR ebay.com OR walmart.com OR target.com OR nike.com OR "
        "adidas.com OR asos.com OR zara.com OR nordstrom.com OR macys.com OR "
        "hm.com OR uniqlo.com OR lululemon.com OR gap.com OR revolve.com OR "
        "farfetch.com OR shein.com OR bloomingdales.com OR net-a-porter.com"
    )
    # EN: original terms + purchase / payment / transaction / "your order" / "thank you for your order"
    # HE: חשבונית (invoice) | קבלה (receipt) | הזמנה (order) | רכישה (purchase) | תשלום (payment)
    subject_terms = (
        'order OR receipt OR invoice OR shipped OR "order confirmation" OR '
        'purchase OR "your order" OR "thank you for your order" OR payment OR transaction OR '
        "חשבונית OR קבלה OR הזמנה OR רכישה OR תשלום"
    )
    # Layer A (email-TYPE gate): -category:promotions EXCLUDES Gmail's Promotions tab at
    # the SOURCE, so promotional / price-drop / abandoned-cart mail is never fetched,
    # filtered, or sent to the LLM — the cheapest possible cut (~95% of the ad junk).
    # We EXCLUDE promotions rather than RESTRICT to category:purchases on purpose: Gmail
    # under-labels Purchases (genuine receipts routinely land in Updates/Primary), so a
    # purchases-only query would DROP real receipts. Exclusion is the low-false-negative
    # lever; the purchases / retailer / subject OR-branches still gather everything else.
    return (
        f"after:{since_date} -category:promotions ("
        "category:purchases "
        f"OR from:({top_domains}) "
        f"OR subject:({subject_terms})"
        ")"
    )


def _list_all_ids(
    client: httpx.Client, token: str, query: str, max_messages: Optional[int] = None
) -> Tuple[List[str], int]:
    """Paginate Gmail messages.list; return (all_message_ids, result_size_estimate).

    ``max_messages`` (DEV-ONLY cap, #5): when set, stop paginating and truncate the id
    list once this many ids have been collected. None (the prod default) = unbounded full
    scan — so the cap is structurally incapable of shrinking a prod scan (the caller only
    passes a value when GMAIL_DEV_SCAN_CAP_ENABLED is explicitly true)."""
    headers = {"Authorization": f"Bearer {token}"}
    params: dict = {"q": query, "maxResults": 500, "fields": _FIELDS_LIST}
    all_ids: List[str] = []
    estimate = 0

    while True:
        for attempt in range(6):
            resp = client.get(
                f"{_GMAIL_BASE}/messages",
                headers=headers,
                params=params,
                timeout=30.0,
            )
            if resp.status_code in (429, 403):
                _sleep_backoff(attempt)
                continue
            resp.raise_for_status()
            break
        else:
            raise RuntimeError("messages.list: max retries exceeded")

        data = resp.json()
        if not estimate:
            estimate = data.get("resultSizeEstimate", 0)
        all_ids.extend(msg["id"] for msg in data.get("messages", []))

        # DEV cap: stop early once we've collected enough (prod passes None -> never).
        if max_messages is not None and len(all_ids) >= max_messages:
            all_ids = all_ids[:max_messages]
            break

        next_page = data.get("nextPageToken")
        if not next_page:
            break
        params = {**params, "pageToken": next_page}

    return all_ids, estimate


def _fetch_one(client: httpx.Client, token: str, msg_id: str) -> Optional[dict]:
    """Fetch one message with exponential backoff on 429/403. None = 404 or max retries."""
    headers = {"Authorization": f"Bearer {token}"}
    params = {"format": "full", "fields": _FIELDS_GET}

    for attempt in range(6):
        resp = client.get(
            f"{_GMAIL_BASE}/messages/{msg_id}",
            headers=headers,
            params=params,
            timeout=30.0,
        )
        if resp.status_code == 404:
            return None
        if resp.status_code in (429, 403):
            _sleep_backoff(attempt)
            continue
        resp.raise_for_status()
        return resp.json()

    logger.warning("message_id=%s: max retries exceeded, skipping", msg_id)
    return None


def _decode_b64(data: str) -> str:
    """URL-safe base64 decode with Gmail API padding fix (omits trailing '=')."""
    pad = "==" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode(data + pad).decode("utf-8", errors="ignore")


def _extract_body(payload: dict) -> str:
    """Recursively extract clean text from a Gmail message payload.

    Prefers text/plain; falls back to text/html via BeautifulSoup.
    Skips attachment parts (those carry an attachmentId, not inline data).
    Handles multipart/mixed, multipart/alternative, multipart/related, etc.
    """
    plain: List[str] = []
    html: List[str] = []

    def _walk(node: dict) -> None:
        mime = node.get("mimeType", "")
        body = node.get("body", {})
        data = body.get("data")

        if data and not body.get("attachmentId"):
            try:
                decoded = _decode_b64(data)
                if mime == "text/plain":
                    plain.append(decoded)
                elif mime == "text/html":
                    html.append(decoded)
            except Exception:
                pass

        for part in node.get("parts", []):
            _walk(part)

    _walk(payload)

    if plain:
        return "\n".join(plain)

    if html:
        soup = BeautifulSoup("\n".join(html), "html.parser")
        return soup.get_text(separator=" ", strip=True)

    return ""


def _process_message(
    client: httpx.Client,
    token: str,
    msg_id: str,
) -> Optional[_MsgResult]:
    """Fetch + parse + Tier-1 filter one message. Returns None on unrecoverable error."""
    raw = _fetch_one(client, token, msg_id)
    if raw is None:
        return None

    payload = raw.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}

    sender = headers.get("from", "")
    subject = headers.get("subject", "")
    body_text = _extract_body(payload)
    # Gmail category labels (labelIds is a TOP-LEVEL message field, not inside payload) —
    # the Tier-1 filter uses them as a hard email-TYPE signal (Layer B).
    labels = raw.get("labelIds", [])

    content_hash = hashlib.sha256(body_text.encode()).hexdigest()[:32]
    kept, _reason = passes_tier1_filter(sender, subject, body_text, labels)
    # Clothing-likeliness is cheap here (headers already parsed) — recorded so the
    # extraction queue can put probable-clothing emails first.
    priority = clothing_priority(sender, subject)

    return _MsgResult(message_id=msg_id, kept=kept, content_hash=content_hash, priority=priority)


def _upsert_processed(
    db: Session,
    user_id: UUID,
    google_account_id: int,
    msg_id: str,
    content_hash: str,
    status: str,
    extract_priority: int = 1,
) -> None:
    """INSERT … ON CONFLICT DO UPDATE for the processed_messages idempotency ledger."""
    stmt = (
        pg_insert(ProcessedMessage)
        .values(
            user_id=user_id,
            google_account_id=google_account_id,
            message_id=msg_id,
            content_hash=content_hash,
            status=status,
            extract_priority=extract_priority,
            processed_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_update(
            constraint="processed_messages_user_id_message_id_key",
            set_={
                "status": status,
                "extract_priority": extract_priority,
                "processed_at": datetime.now(timezone.utc),
            },
        )
    )
    db.execute(stmt)


# ---------------------------------------------------------------------------
# Core worker (private)
# ---------------------------------------------------------------------------

def _run_ingest_core(
    user_id: UUID,
    google_account: GoogleAccount,
    sync_id: UUID,
    db: Session,
    finalize: bool = True,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> IngestStats:
    """List → skip-known → fetch → Tier-1 filter → persist → return IngestStats.

    The IngestRun row identified by sync_id must already exist in DB.
    db is a session owned by the caller (not shared with any request session).

    finalize=False leaves run.status='running' on success so the caller can chain
    the extraction phase onto the SAME run (the full background pipeline). The
    returned IngestStats.status is still 'completed' to report the fetch phase
    outcome. Errors are always terminal regardless of finalize.

    ``should_cancel``: cooperative-cancellation probe checked at each fetch-batch
    boundary. When it returns True the loop stops promptly (within one batch),
    leaves the run 'running' (never finalized), and returns status='cancelled'.
    Per-batch commits mean partial progress is already durable and idempotent, so
    a restarted worker resumes exactly-once. Default None -> never cancels
    (the legacy BackgroundTasks path is unaffected).
    """
    t0 = time.time()

    run: Optional[IngestRun] = (
        db.query(IngestRun).filter(IngestRun.sync_id == sync_id).first()
    )
    if not run:
        logger.error("sync_id=%s: IngestRun not found", sync_id)
        return IngestStats(
            sync_id=sync_id, status="error", total_listed=0, total_estimate=0,
            skipped=0, fetched=0, filtered=0, errors=0, elapsed=0.0,
        )

    try:
        access_token = ensure_fresh_token(google_account, db)
    except Exception:
        logger.error("sync_id=%s: token refresh failed", sync_id)
        run.status = "error"
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        return IngestStats(
            sync_id=sync_id, status="error", total_listed=0, total_estimate=0,
            skipped=0, fetched=0, filtered=0, errors=0, elapsed=time.time() - t0,
        )

    # DEV-ONLY scan cap (#5): a dev iterating locally can bound the scan to a short window
    # + a message ceiling so they don't fetch + LLM-extract a full 2-year mailbox. This is
    # a PURE BOUND (no filter/extraction change) and is STRUCTURALLY off in prod — the
    # flag defaults False, and both bounds fall back to the full scan when it is unset.
    dev_cap_messages: Optional[int] = None
    if settings.GMAIL_DEV_SCAN_CAP_ENABLED:
        dev_days = max(1, int(settings.GMAIL_DEV_SCAN_MAX_DAYS))
        since = datetime.utcnow() - timedelta(days=dev_days)
        dev_cap_messages = max(1, int(settings.GMAIL_DEV_SCAN_MAX_MESSAGES))
        logger.warning(
            "sync_id=%s: DEV SCAN CAP ACTIVE — window=%dd max_messages=%d (never enable in prod)",
            sync_id, dev_days, dev_cap_messages,
        )
    else:
        since = default_since()
    query = _build_query(since)
    ga_id = google_account.id

    logger.info("sync_id=%s: starting ingest, window since %s", sync_id, since.date())

    try:
        # httpx.Client is thread-safe (httpcore pool uses locking internally).
        with httpx.Client(
            limits=httpx.Limits(
                max_connections=_MAX_CONCURRENT + 10,
                max_keepalive_connections=_MAX_CONCURRENT,
            )
        ) as http:

            # ----------------------------------------------------------------
            # Phase 1: paginate Gmail to collect all matching message IDs
            # ----------------------------------------------------------------
            logger.info("sync_id=%s: listing message IDs...", sync_id)
            all_ids, estimate = _list_all_ids(http, access_token, query, dev_cap_messages)

            logger.info(
                "sync_id=%s: resultSizeEstimate=%d list_total=%d",
                sync_id, estimate, len(all_ids),
            )

            run.total_estimate = estimate or len(all_ids)
            db.commit()

            # ----------------------------------------------------------------
            # Phase 2: idempotency — skip messages already in processed_messages
            # ----------------------------------------------------------------
            already_done: Set[str] = set()
            _CHUNK = 1_000
            for i in range(0, len(all_ids), _CHUNK):
                chunk = all_ids[i : i + _CHUNK]
                rows = (
                    db.query(ProcessedMessage.message_id)
                    .filter(
                        ProcessedMessage.user_id == user_id,
                        ProcessedMessage.message_id.in_(chunk),
                    )
                    .all()
                )
                already_done.update(r[0] for r in rows)

            to_fetch = [mid for mid in all_ids if mid not in already_done]
            skipped = len(already_done)

            logger.info(
                "sync_id=%s: %d total | %d skipped (idempotency) | %d to fetch",
                sync_id, len(all_ids), skipped, len(to_fetch),
            )

            fetched_count = 0   # passed Tier-1
            filtered_out = 0    # failed Tier-1
            error_count = 0     # 404 / max-retries
            cancelled = False

            # ----------------------------------------------------------------
            # Phase 3: fetch + Tier-1 filter in concurrent batches of _BATCH_SIZE
            # ----------------------------------------------------------------
            for batch_start in range(0, len(to_fetch), _BATCH_SIZE):
                if should_cancel is not None and should_cancel():
                    logger.info(
                        "sync_id=%s: cancellation requested — stopping fetch at %d/%d",
                        sync_id, batch_start, len(to_fetch),
                    )
                    cancelled = True
                    break
                batch = to_fetch[batch_start : batch_start + _BATCH_SIZE]
                n_workers = min(_MAX_CONCURRENT, len(batch))

                batch_results: List[_MsgResult] = []
                with ThreadPoolExecutor(max_workers=n_workers) as pool:
                    futures = {
                        pool.submit(_process_message, http, access_token, mid): mid
                        for mid in batch
                    }
                    for future in as_completed(futures):
                        mid = futures[future]
                        try:
                            result = future.result()
                            if result is not None:
                                batch_results.append(result)
                            else:
                                error_count += 1  # 404 or max retries
                        except Exception as exc:
                            error_count += 1
                            # Log message_id only — never subject/body
                            logger.warning(
                                "sync_id=%s message_id=%s: error (%s)",
                                sync_id, mid, type(exc).__name__,
                            )

                # Persist processed_messages and update run counters
                for r in batch_results:
                    status = "fetched" if r.kept else "filtered_out"
                    _upsert_processed(
                        db, user_id, ga_id, r.message_id, r.content_hash, status,
                        extract_priority=r.priority,
                    )
                    if r.kept:
                        fetched_count += 1
                    else:
                        filtered_out += 1

                db.commit()

                run.fetched_count = fetched_count
                run.filtered_count = filtered_out
                db.commit()

                done_so_far = batch_start + len(batch)
                pct = done_so_far * 100 // max(len(to_fetch), 1)
                logger.info(
                    "sync_id=%s: %d%% — fetched=%d filtered_out=%d errors=%d",
                    sync_id, pct, fetched_count, filtered_out, error_count,
                )

        # Cooperative cancel: leave the run 'running' (resumable) and report
        # 'cancelled' so run_full_ingest stops before extraction. Partial fetch
        # progress is already committed per batch and idempotency-skipped on replay.
        if cancelled:
            return IngestStats(
                sync_id=sync_id, status="cancelled",
                total_listed=len(all_ids), total_estimate=estimate,
                skipped=skipped, fetched=fetched_count, filtered=filtered_out,
                errors=error_count, elapsed=time.time() - t0,
            )

        # Finalize the run only when this fetch is the whole job. When chained
        # before extraction (finalize=False) the run stays 'running' so the
        # extraction phase can complete it on the same sync_id.
        if finalize:
            run.status = "completed"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()

        elapsed = time.time() - t0
        logger.info(
            "sync_id=%s: DONE. fetched=%d filtered_out=%d skipped=%d errors=%d elapsed=%.1fs",
            sync_id, fetched_count, filtered_out, skipped, error_count, elapsed,
        )

        return IngestStats(
            sync_id=sync_id,
            status="completed",
            total_listed=len(all_ids),
            total_estimate=estimate,
            skipped=skipped,
            fetched=fetched_count,
            filtered=filtered_out,
            errors=error_count,
            elapsed=elapsed,
        )

    except Exception as exc:
        elapsed = time.time() - t0
        logger.error(
            "sync_id=%s: ingest error — %s: %s", sync_id, type(exc).__name__, exc
        )
        try:
            run.status = "error"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            pass
        return IngestStats(
            sync_id=sync_id, status="error",
            total_listed=0, total_estimate=0,
            skipped=0, fetched=0, filtered=0, errors=0,
            elapsed=elapsed,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_ingest_sync(
    user_id: UUID,
    db: Session,
    sync_id: Optional[UUID] = None,
    finalize: bool = True,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> IngestStats:
    """Create IngestRun (if needed) + run full sync + return IngestStats.

    Two callers:
    - Route (via run_full_ingest): passes the sync_id it pre-created so the
      status endpoint can return it before the sync starts, with finalize=False
      so the extraction phase completes the same run.
    - Dev script: passes no sync_id; the IngestRun row is created here.

    No behavior change for the standalone path (finalize defaults True).
    """
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

    return _run_ingest_core(
        user_id=user_id,
        google_account=account,
        sync_id=sync_id,
        db=db,
        finalize=finalize,
        should_cancel=should_cancel,
    )


def run_full_ingest(
    user_id: UUID,
    db: Session,
    sync_id: UUID,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> None:
    """Run the COMPLETE pipeline on one sync_id: fetch → Tier-1 filter → extract → stage.

    This is the background job behind POST /gmail/ingest/start. It chains the two
    proven phases onto a single IngestRun so /gmail/ingest/status reflects progress
    all the way through extraction:

      Phase A  run_ingest_sync(finalize=False)  -> writes processed_messages, bumps
               fetched_count / filtered_count, leaves run.status='running'.
      Phase B  run_extraction_sync(sync_id)     -> LLM-extracts the status='fetched'
               messages, stages candidates with FAST-tier images, bumps
               extracted_count, and finalizes the run (status='completed', or 'error').
               Finalizing here is what makes the deck appear.
      Phase C  run_image_fill(user_id)          -> NON-BLOCKING background fill: runs the
               SLOW image tiers (og:image / feed / search) over the still-imageless
               candidates and self-heals pending confirmed items cache-first, streaming
               images onto cards as they resolve. Runs AFTER the deck is shown (the run
               is already 'completed'); the frontend polls /candidates to swap images in.

    Phase A errors are terminal (the run is already marked 'error') and skip phase B/C.
    The fetch/filter/extract logic itself is unchanged — this only sequences them.

    ``should_cancel`` (cooperative cancellation, used by the durable-job worker on
    graceful shutdown) is threaded into every phase and checked between them: on
    cancel each phase stops at a safe boundary leaving the run 'running', and this
    function returns early WITHOUT marking anything failed — the worker re-queues
    the job so a restart resumes it exactly-once (all progress is idempotent).
    """
    # Late import: extraction_service imports private helpers from this module, so a
    # module-level import here would be circular.
    from app.gmail_closet.extraction_service import run_extraction_sync

    fetch_stats = run_ingest_sync(
        user_id=user_id, db=db, sync_id=sync_id, finalize=False, should_cancel=should_cancel)
    if fetch_stats.status == "cancelled":
        logger.info("sync_id=%s: fetch cancelled — run left 'running', will resume", sync_id)
        return
    if fetch_stats.status != "completed":
        logger.error("sync_id=%s: fetch phase failed; skipping extraction", sync_id)
        return
    if should_cancel is not None and should_cancel():
        logger.info("sync_id=%s: cancelled between fetch and extraction — will resume", sync_id)
        return

    ext_stats = run_extraction_sync(
        user_id=user_id, db=db, sync_id=sync_id, should_cancel=should_cancel)
    logger.info(
        "sync_id=%s: full pipeline done. fetched=%d filtered=%d skipped=%d "
        "fetch_err=%d | emails→llm=%d staged=%d rejected=%d llm_err=%d status=%s",
        sync_id,
        fetch_stats.fetched, fetch_stats.filtered, fetch_stats.skipped, fetch_stats.errors,
        ext_stats.emails_to_llm, ext_stats.candidates_staged, ext_stats.rejected_msgs,
        ext_stats.llm_errors, ext_stats.status,
    )

    # Phase C: background image fill + self-heal. The run is already finalized, so a
    # failure here can NEVER affect the deck; run_image_fill is itself best-effort and
    # never raises. Skipped only when extraction itself errored or was cancelled.
    if ext_stats.status != "completed":
        return
    from app.gmail_closet.image_fill_service import run_image_fill

    fill_stats = run_image_fill(
        user_id=user_id, db=db, sync_id=sync_id, should_cancel=should_cancel)
    logger.info(
        "sync_id=%s: image fill done. cache=%d slow=%d exhausted=%d (candidates=%d confirmed=%d)",
        sync_id, fill_stats.cache_filled, fill_stats.slow_filled, fill_stats.exhausted,
        fill_stats.candidates_seen, fill_stats.confirmed_seen,
    )


def ingest_background(user_id_str: str, sync_id_str: str) -> None:
    """Background task entry point (Starlette runs sync tasks in a thread pool).

    Creates its own DB session, fully decoupled from the request session
    (which is closed before this runs), then runs the full fetch→extract pipeline.
    """
    from app.db import SessionLocal  # late import avoids circular import at module level

    db = SessionLocal()
    try:
        user_id = UUID(user_id_str)
        sync_id = UUID(sync_id_str)
        run_full_ingest(user_id=user_id, db=db, sync_id=sync_id)
    except Exception as exc:
        logger.error("ingest_background: unhandled error — %s: %s", type(exc).__name__, exc)
    finally:
        db.close()
