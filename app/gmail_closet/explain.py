"""Read-only Tier-0/Tier-1 audit used by scripts/dev_run_ingest.py --explain.

explain_fetch(user_id, db) -> ExplainResult

Runs the same Tier-0 query and Tier-1 filter as the real ingest but writes
NOTHING to the database (no processed_messages rows, no ingest_runs row).
Token refresh may update google_accounts — that is normal OAuth maintenance,
not ingestion data.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from uuid import UUID

import httpx
from sqlalchemy.orm import Session

from app.gmail_closet.fetch_service import (
    _GMAIL_BASE,
    _BATCH_SIZE,
    _MAX_CONCURRENT,
    _fetch_one,
    _extract_body,
    _list_all_ids,
    _sleep_backoff,
    _build_query,
)
from app.gmail_closet.gmail_oauth_client import default_since
from app.gmail_closet.gmail_oauth_service import ensure_fresh_token
from app.gmail_closet.receipt_filter import passes_tier1_filter
from app.models import GoogleAccount

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Return types
# ---------------------------------------------------------------------------

@dataclass
class ExplainRow:
    message_id: str
    sender: str    # From header — shown in table
    subject: str   # Subject header — shown in table; body is never logged/shown
    kept: bool     # Tier-1 decision
    reason: str    # Tier-1 reason code


@dataclass
class ExplainResult:
    rows: List[ExplainRow]   # KEPT first, then DROPPED; sorted by sender within groups
    query: str               # Tier-0 query used (for reference)
    tier0_count: int         # exact count of messages matched by Tier-0 query
    superset_count: int      # resultSizeEstimate from one superset list call (approximate)
    elapsed: float           # wall-clock seconds for the full explain run


# ---------------------------------------------------------------------------
# Superset query
# ---------------------------------------------------------------------------

def _build_superset_query(since: datetime) -> str:
    """Strict superset of the Tier-0 query: same structure, even broader subject list.

    The new Tier-0 already includes: order, receipt, invoice, shipped, "order confirmation",
    purchase, "your order", "thank you for your order", payment, transaction, plus Hebrew
    receipt terms (חשבונית, קבלה, הזמנה, רכישה, תשלום).

    This superset adds: tracking, delivered, confirmation, billing, "order number",
    "order summary", plus Hebrew confirmation/summary terms not in Tier-0.
    """
    since_date = since.strftime("%Y/%m/%d")
    top_domains = (
        "amazon.com OR ebay.com OR walmart.com OR target.com OR nike.com OR "
        "adidas.com OR asos.com OR zara.com OR nordstrom.com OR macys.com OR "
        "hm.com OR uniqlo.com OR lululemon.com OR gap.com OR revolve.com OR "
        "farfetch.com OR shein.com OR bloomingdales.com OR net-a-porter.com"
    )
    # All Tier-0 subject terms + superset-only additions
    all_subjects = (
        # Tier-0 EN terms:
        'order OR receipt OR invoice OR shipped OR "order confirmation" OR '
        'purchase OR "your order" OR "thank you for your order" OR payment OR transaction OR '
        # Tier-0 HE terms:
        "חשבונית OR קבלה OR הזמנה OR רכישה OR תשלום OR "
        # Superset-only EN additions:
        'tracking OR delivered OR confirmation OR billing OR "order number" OR "order summary" OR '
        # Superset-only HE additions (not in Tier-0):
        "אישור OR סיכום OR מספר קבלה"
    )
    return (
        f"after:{since_date} ("
        "category:purchases "
        f"OR from:({top_domains}) "
        f"OR subject:({all_subjects})"
        ")"
    )


def _count_superset(client: httpx.Client, token: str, query: str) -> int:
    """One messages.list call → resultSizeEstimate for the superset query.

    Uses a single page request (maxResults=1) so quota cost is 5u and latency
    is <1 s. The result is an estimate, noted as such in the output.
    No message bodies are fetched.
    """
    headers = {"Authorization": f"Bearer {token}"}
    params = {"q": query, "maxResults": 1, "fields": "resultSizeEstimate"}
    for attempt in range(5):
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
        return resp.json().get("resultSizeEstimate", 0)
    return 0


# ---------------------------------------------------------------------------
# Per-message helper (no DB writes)
# ---------------------------------------------------------------------------

def _explain_one(
    client: httpx.Client,
    token: str,
    msg_id: str,
) -> Optional[ExplainRow]:
    """Fetch + parse + Tier-1 filter one message. Never writes to DB."""
    raw = _fetch_one(client, token, msg_id)
    if raw is None:
        return None

    payload = raw.get("payload", {})
    hdr_list = payload.get("headers", [])
    headers = {h["name"].lower(): h["value"] for h in hdr_list}

    sender = headers.get("from", "")
    subject = headers.get("subject", "")
    body_text = _extract_body(payload)   # used only for Tier-1; never logged/shown

    kept, reason = passes_tier1_filter(sender, subject, body_text)

    return ExplainRow(
        message_id=msg_id,
        sender=sender,
        subject=subject,
        kept=kept,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def explain_fetch(user_id: UUID, db: Session) -> ExplainResult:
    """Read-only Tier-0/Tier-1 audit.

    1. Paginates the current Tier-0 query to get the exact message list.
    2. Fetches all bodies concurrently and applies the Tier-1 filter.
    3. Issues ONE extra messages.list call for the superset query (count only).
    4. Returns ExplainResult with every row + the count delta.

    Nothing is written to processed_messages, ingest_runs, or clothing_items.
    Bodies are used only to run the filter — they are never returned or logged.
    """
    account: Optional[GoogleAccount] = (
        db.query(GoogleAccount)
        .filter(GoogleAccount.user_id == user_id)
        .first()
    )
    if not account or not account.refresh_token:
        raise ValueError(f"No Gmail connection for user {user_id}. Connect via /gmail/oauth/start.")

    access_token = ensure_fresh_token(account, db)
    since = default_since()
    query = _build_query(since)
    superset_query = _build_superset_query(since)

    t0 = time.time()
    rows: List[ExplainRow] = []

    with httpx.Client(
        limits=httpx.Limits(
            max_connections=_MAX_CONCURRENT + 10,
            max_keepalive_connections=_MAX_CONCURRENT,
        )
    ) as http:

        # Phase 1: collect all Tier-0 message IDs (paginated → exact count)
        logger.info("explain: listing Tier-0 message IDs...")
        all_ids, _ = _list_all_ids(http, access_token, query)
        tier0_count = len(all_ids)
        logger.info("explain: Tier-0 list_total=%d", tier0_count)

        # Phase 2: fetch bodies + Tier-1 filter concurrently, no DB writes
        for batch_start in range(0, len(all_ids), _BATCH_SIZE):
            batch = all_ids[batch_start : batch_start + _BATCH_SIZE]
            n_workers = min(_MAX_CONCURRENT, len(batch))

            with ThreadPoolExecutor(max_workers=n_workers) as pool:
                futures = {
                    pool.submit(_explain_one, http, access_token, mid): mid
                    for mid in batch
                }
                for future in as_completed(futures):
                    mid = futures[future]
                    try:
                        row = future.result()
                        if row is not None:
                            rows.append(row)
                    except Exception as exc:
                        logger.warning(
                            "explain message_id=%s: fetch error (%s)",
                            mid, type(exc).__name__,
                        )

            done = batch_start + len(batch)
            pct = done * 100 // max(tier0_count, 1)
            logger.info("explain: %d%% (%d/%d fetched+filtered)", pct, done, tier0_count)

        # Phase 3: superset count — one list call, no body fetches
        logger.info("explain: counting superset query (1 list call)...")
        superset_count = _count_superset(http, access_token, superset_query)
        logger.info("explain: superset_count=%d (estimate)", superset_count)

    # Sort: KEPT first, DROPPED second; within each group, alphabetical by sender
    rows.sort(key=lambda r: (not r.kept, r.sender.lower()))

    return ExplainResult(
        rows=rows,
        query=query,
        tier0_count=tier0_count,
        superset_count=superset_count,
        elapsed=time.time() - t0,
    )
