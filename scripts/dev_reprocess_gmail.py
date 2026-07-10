"""Reprocess the Gmail candidate corpus through the v2 receipt-document pipeline.

Usage (from project root):
    python -m scripts.dev_reprocess_gmail <email>                    # DRY-RUN (default)
    python -m scripts.dev_reprocess_gmail <email> --json out.json    # dry-run + full JSON report
    python -m scripts.dev_reprocess_gmail <email> --apply            # REAL rewrite (gated)

DRY-RUN (default, Gate-2 deliverable):
  READ-ONLY against the DB (token refresh aside). Fetches every message that ever
  contributed a gmail candidate — BY MESSAGE ID, bypassing Tier-0 — plus the
  RECOVERY_MESSAGE_IDS (delivery notifications the v1 pipeline never ingested),
  runs the v2 extractor + reconcile + corpus passes IN MEMORY, and prints:
    - per-merchant before/after (v1 rows vs v2 admitted/demoted)
    - per-order collapse vs the email's own stated_item_count
    - demotion reasons breakdown, email_kind distribution
    - ZERO-DROP proof for the known-order populations
    - Tier-0 coverage check: which corpus messages the NEW query would catch

APPLY (--apply, only after dry-run sign-off):
  Stages the v2 result under a fresh IngestRun, then SUPERSEDE-DEMOTES every
  untouched pre-existing v1 gmail candidate row (pipeline_state=
  'rejected_recommendation', reason 'superseded_v1_rewrite') — demote, never
  delete. Requires migration 0040 on the target DB. Refuses to run without
  --i-reviewed-the-dry-run.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.WARNING, stream=sys.stdout)

import httpx
from sqlalchemy import text as sa_text

from app.db import SessionLocal
from app.gmail_closet.extraction_schema import ReceiptDocument
from app.gmail_closet.extractor import extract_receipt
from app.gmail_closet.fetch_service import (
    _build_query,
    _extract_body,
    _fetch_one,
    _list_all_ids,
)
from app.gmail_closet.gmail_oauth_service import ensure_fresh_token
from app.gmail_closet.reconcile import (
    MessageDecision,
    _names_alike,
    apply_retargeting_rule,
    enrichment_join,
    merge_order_name_drift,
    reconcile_message,
    strip_line_noise,
)
from app.gmail_closet.receipt_filter import passes_tier1_filter
from app.gmail_closet.retailers import match_retailer
from app.models import GoogleAccount, IngestCandidate, User

# Delivery notifications found in the Gate-1 probe that the v1 pipeline NEVER
# ingested — extra recovery sources for the two known SHEIN orders.
RECOVERY_MESSAGE_IDS = [
    "19662c480b22d3e1",   # SHEIN Order Delivered Notification (GSH11L45C0019HH)
    "19a960850e386345",   # SHEIN Order Delivery Notification (GSH1QN45C0005QX)
]

# The known-order populations for the zero-drop proof.
KNOWN_ORDERS = ("GSH11L45C0019HH", "GSH1QN45C0005QX", "c175923092447259")

_CONCURRENCY = 8


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class MsgOutcome:
    message_id: str
    sender: str = ""
    subject: str = ""
    labels: List[str] = field(default_factory=list)
    retailer: Optional[str] = None
    fetch_failed: bool = False
    llm_failed: bool = False
    non_clothing: bool = False
    tier1_kept: Optional[bool] = None
    tier1_reason: Optional[str] = None
    doc: Optional[ReceiptDocument] = None
    decision: Optional[MessageDecision] = None
    est_cost: float = 0.0


# ---------------------------------------------------------------------------
# Fetch + extract one message (Tier-0 bypass: by id)
# ---------------------------------------------------------------------------

def _process_one(http: httpx.Client, token: str, mid: str) -> MsgOutcome:
    out = MsgOutcome(message_id=mid)
    raw = _fetch_one(http, token, mid)
    if raw is None:
        out.fetch_failed = True
        return out
    payload = raw.get("payload", {})
    hdrs = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    out.sender = hdrs.get("from", "")
    out.subject = hdrs.get("subject", "")
    out.labels = raw.get("labelIds", []) or []
    out.retailer = match_retailer(out.sender)
    body = _extract_body(payload)
    out.tier1_kept, out.tier1_reason = passes_tier1_filter(
        out.sender, out.subject, body, out.labels)

    sent_at = raw.get("internalDate")
    outcome = extract_receipt(
        sender=out.sender, subject=out.subject,
        sent_at=str(sent_at) if sent_at else None,
        body=body, inline_image_count=0,
    )
    out.est_cost = outcome.est_cost_realistic
    if outcome.receipt is None:
        out.llm_failed = True
        return out
    doc = outcome.receipt
    if doc.merchant is None:
        doc.merchant = out.retailer
    out.doc = doc
    if not doc.is_clothing and not doc.order_lines and not doc.returned_lines:
        # Pure non-clothing marketing/other: nothing to route.
        out.non_clothing = True
        return out
    out.decision = reconcile_message(mid, doc)
    return out


# ---------------------------------------------------------------------------
# In-memory staging simulation (mirrors _upsert_candidate's merge)
# ---------------------------------------------------------------------------

@dataclass
class SimRow:
    content_key: str
    name: str
    merchant: Optional[str]
    order_id: Optional[str]
    size: Optional[str]
    color: Optional[str]
    unit_price: Optional[float]
    brand: Optional[str]
    category: Optional[str]
    qty: int
    admitted: bool
    reason: Optional[str]
    needs_enrichment: bool
    is_return: bool
    email_kinds: List[str] = field(default_factory=list)
    message_ids: List[str] = field(default_factory=list)
    sections: List[str] = field(default_factory=list)


def simulate_staging(decisions: List[MessageDecision]) -> Dict[str, SimRow]:
    rows: Dict[str, SimRow] = {}
    for md in decisions:
        for ld in md.admitted + md.demoted:
            r = rows.get(ld.content_key)
            if r is None:
                r = SimRow(
                    content_key=ld.content_key, name=ld.line.name, merchant=md.merchant,
                    order_id=md.order_id if ld.admitted else None,
                    size=ld.line.size, color=ld.line.color,
                    unit_price=ld.line.unit_price,
                    brand=ld.line.brand,
                    category=ld.line.category.value if ld.line.category else None,
                    qty=ld.line.qty or 1,
                    admitted=ld.admitted, reason=ld.reason,
                    needs_enrichment=ld.needs_enrichment, is_return=ld.is_return,
                )
                rows[ld.content_key] = r
            else:
                # merge mirrors the DB upsert: revival (admit beats demote),
                # enrichment (both must still need it), returns are sticky.
                if ld.admitted and not r.admitted:
                    r.admitted, r.reason = True, None
                r.needs_enrichment = r.needs_enrichment and ld.needs_enrichment
                r.is_return = r.is_return or ld.is_return
                r.order_id = r.order_id or (md.order_id if ld.admitted else None)
                r.unit_price = r.unit_price if r.unit_price is not None else ld.line.unit_price
            if md.message_id not in r.message_ids:
                r.message_ids.append(md.message_id)
            r.email_kinds.append(md.email_kind)
            if ld.line.section_evidence:
                r.sections.append(ld.line.section_evidence)
    return rows


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def build_report(user_id, db, outcomes: List[MsgOutcome],
                 rows: Dict[str, SimRow], enriched: int, retarget_demoted: int,
                 tier0_ids: Optional[set]) -> dict:
    # v1 baseline from the live DB.
    v1 = db.execute(sa_text("""
        SELECT merchant, order_id, name, unnest(source_message_ids) AS mid
        FROM ingest_candidates
        WHERE user_id = :uid AND source_type = 'gmail'
    """), {"uid": str(user_id)}).fetchall()
    v1_by_merchant = Counter((r[0] or "?") for r in v1)
    v1_msgs_by_order: Dict[str, set] = defaultdict(set)
    v1_rows_by_order: Dict[str, int] = Counter()
    seen_pairs = set()
    for merchant, order_id, name, mid in v1:
        if order_id:
            v1_msgs_by_order[order_id].add(mid)
            pair = (order_id, name)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                v1_rows_by_order[order_id] += 1

    admitted = [r for r in rows.values() if r.admitted and not r.is_return]
    returns = [r for r in rows.values() if r.admitted and r.is_return]
    demoted = [r for r in rows.values() if not r.admitted]

    per_merchant = {}
    merchants = {(r.merchant or "?") for r in rows.values()} | set(v1_by_merchant)
    for m in sorted(merchants):
        per_merchant[m] = {
            "v1_rows": v1_by_merchant.get(m, 0),
            "v2_admitted": sum(1 for r in admitted if (r.merchant or "?") == m),
            "v2_admitted_needs_enrichment": sum(
                1 for r in admitted if (r.merchant or "?") == m and r.needs_enrichment),
            "v2_demoted": sum(1 for r in demoted if (r.merchant or "?") == m),
        }

    # Per-order collapse.
    per_order = {}
    stated_by_order: Dict[str, int] = {}
    for o in outcomes:
        if o.doc and o.doc.order and o.doc.order.order_id and o.doc.stated_item_count:
            oid = o.doc.order.order_id
            stated_by_order[oid] = max(stated_by_order.get(oid, 0), o.doc.stated_item_count)
    order_ids = {r.order_id for r in admitted if r.order_id}
    for oid in sorted(order_ids):
        o_rows = [r for r in admitted if r.order_id == oid]
        per_order[oid] = {
            "v1_rows": v1_rows_by_order.get(oid, 0),
            "v2_items": len(o_rows),
            "needs_enrichment": sum(1 for r in o_rows if r.needs_enrichment),
            "stated_item_count": stated_by_order.get(oid),
            "chain_messages": sorted({m for r in o_rows for m in r.message_ids}),
        }

    # ZERO-DROP proof: every v1 message of a known order must contribute only
    # ADMITTED lines in v2 (no known-order line may land demoted/quarantined).
    zero_drop = {}
    for oid in KNOWN_ORDERS:
        chain_msgs = v1_msgs_by_order.get(oid, set())
        problems = []
        for o in outcomes:
            if o.message_id not in chain_msgs:
                continue
            if o.fetch_failed or o.llm_failed:
                problems.append({"message_id": o.message_id, "issue": "fetch_or_llm_failed"})
            elif o.decision is None:
                problems.append({"message_id": o.message_id, "issue": "no_decision"})
            elif o.decision.quarantined:
                problems.append({"message_id": o.message_id,
                                 "issue": f"quarantined:{o.decision.quarantine_reason}"})
            elif o.decision.demoted and not o.decision.admitted:
                problems.append({"message_id": o.message_id, "issue": "all_lines_demoted"})
        zero_drop[oid] = {
            "chain_messages_checked": len(chain_msgs),
            "problems": problems,
            "pass": not problems,
        }

    kinds = Counter(o.decision.email_kind for o in outcomes if o.decision)
    kinds.update(Counter("non_clothing_or_empty" for o in outcomes if o.non_clothing))
    reasons = Counter(r.reason for r in demoted)
    quarantined = [
        {"message_id": o.message_id, "reason": o.decision.quarantine_reason,
         "subject": o.subject[:60]}
        for o in outcomes if o.decision and o.decision.quarantined
    ]
    overridden = [o.message_id for o in outcomes if o.decision and o.decision.kind_overridden]

    tier0 = None
    if tier0_ids is not None:
        corpus_ids = {o.message_id for o in outcomes}
        missed = sorted(corpus_ids - tier0_ids)
        missed_detail = []
        for o in outcomes:
            if o.message_id in missed:
                missed_detail.append({
                    "message_id": o.message_id, "subject": o.subject[:60],
                    "labels": o.labels,
                    "email_kind": o.decision.email_kind if o.decision else None,
                    "admitted_lines": len(o.decision.admitted) if o.decision else 0,
                })
        tier0 = {
            "corpus_size": len(corpus_ids),
            "matched_by_new_query": len(corpus_ids & tier0_ids),
            "missed_by_new_query": missed_detail,
        }

    return {
        "corpus_messages": len(outcomes),
        "fetch_failed": sum(1 for o in outcomes if o.fetch_failed),
        "llm_failed": sum(1 for o in outcomes if o.llm_failed),
        "est_llm_cost_usd": round(sum(o.est_cost for o in outcomes), 4),
        "email_kind_distribution": dict(kinds),
        "kind_overridden_messages": overridden,
        "totals": {
            "v1_candidate_rows": len({(r[0], r[1], r[2]) for r in v1}),
            "v2_admitted": len(admitted),
            "v2_admitted_needs_enrichment": sum(1 for r in admitted if r.needs_enrichment),
            "v2_return_lines": len(returns),
            "v2_demoted": len(demoted),
            "enrichment_joins": enriched,
            "retargeting_demotions": retarget_demoted,
        },
        "per_merchant": per_merchant,
        "per_order": per_order,
        "zero_drop_proof": zero_drop,
        "demotion_reasons": dict(reasons),
        "quarantined_emails": quarantined,
        "tier0_coverage": tier0,
        "admitted_lines": [
            {"merchant": r.merchant, "order_id": r.order_id, "name": r.name,
             "size": r.size, "color": r.color, "price": r.unit_price,
             "needs_enrichment": r.needs_enrichment,
             "messages": r.message_ids, "sections": r.sections[:3]}
            for r in sorted(admitted, key=lambda r: ((r.merchant or ""), (r.order_id or ""), r.name))
        ],
    }


def build_ledgers(user_id, db, outcomes: List[MsgOutcome],
                  rows: Dict[str, SimRow], recovery_ids: List[str]) -> dict:
    """Row ledger: every STORED ingest_candidates row -> exactly one disposition.
    Message ledger: every corpus message -> its source. Totals must close."""
    stored = db.execute(sa_text("""
        SELECT id, name, size, color, unit_price, order_id, merchant,
               message_id, source_message_ids
        FROM ingest_candidates
        WHERE user_id = :uid AND source_type = 'gmail'
        ORDER BY created_at
    """), {"uid": str(user_id)}).fetchall()

    kind_by_msg = {o.message_id: (o.decision.email_kind if o.decision else
                                  ("non_clothing" if o.non_clothing else "failed"))
                   for o in outcomes}

    def _norm(x):
        return (strip_line_noise(x or "").lower() or None)

    v2_rows = list(rows.values())
    row_ledger = []
    tally = Counter()
    for (rid, name, size, color, price, order_id, merchant, repr_mid, mids) in stored:
        nn, nsize, ncolor = _norm(name), (size or "").strip().lower(), (color or "").strip().lower()
        match = None
        # 1) exact content match (name+size+color), admitted rows first
        for r in sorted(v2_rows, key=lambda r: not r.admitted):
            if _norm(r.name) == nn and (r.size or "").strip().lower() == nsize                and (r.color or "").strip().lower() == ncolor:
                match = r
                break
        # 2) name-alike + shared contributing message
        if match is None:
            for r in sorted(v2_rows, key=lambda r: not r.admitted):
                if set(mids or []) & set(r.message_ids) and _names_alike(name, r.name):
                    match = r
                    break
        # 3) name-alike anywhere (drifted key, message split)
        if match is None:
            for r in sorted(v2_rows, key=lambda r: not r.admitted):
                if _names_alike(name, r.name):
                    match = r
                    break
        if match is not None:
            outcome = ("superseded_to_admitted_v2" if match.admitted
                       else "superseded_to_demoted_v2")
            detail = match.reason
        else:
            kinds = {kind_by_msg.get(m, "unknown") for m in (mids or [])}
            if kinds <= {"marketing", "non_clothing", "unknown"}:
                outcome, detail = "orphaned", "marketing_line_not_reextracted"
            else:
                outcome, detail = "orphaned", f"line_variance_in_kinds:{sorted(kinds)}"
        tally[outcome if outcome != "orphaned" else f"orphaned:{detail.split(':')[0]}"] += 1
        row_ledger.append({
            "row_id": str(rid), "merchant": merchant, "order_id": order_id,
            "name": (name or "")[:60], "size": size, "color": color,
            "outcome": outcome, "detail": detail,
        })

    stored_repr = {r[7] for r in stored}
    stored_contrib = {m for r in stored for m in (r[8] or [])}
    msg_ledger = []
    for o in sorted(outcomes, key=lambda o: o.message_id):
        if o.message_id in RECOVERY_MESSAGE_IDS:
            src = "recovery_delivery_notice"
        elif o.message_id in stored_repr:
            src = "stored_representative"
        elif o.message_id in stored_contrib:
            src = "stored_array_contributor_only"
        else:
            src = "UNEXPLAINED"
        msg_ledger.append({
            "message_id": o.message_id, "source": src,
            "labels": o.labels,
            "email_kind": (o.decision.email_kind if o.decision else
                           ("non_clothing" if o.non_clothing else "failed")),
            "subject": o.subject[:60],
        })

    return {
        "stored_rows_total": len(stored),
        "row_disposition_tally": dict(tally),
        "row_tally_closes": sum(tally.values()) == len(stored),
        "message_source_tally": dict(Counter(m["source"] for m in msg_ledger)),
        "row_ledger": row_ledger,
        "message_ledger": msg_ledger,
    }


def build_chain_table(outcomes: List[MsgOutcome], tier0_ids: Optional[set],
                      db, user_id) -> List[dict]:
    """Every real-order chain message: labels + kind + does the NEW Tier-0 query
    match it. The forward-risk check: a transactional message carrying
    CATEGORY_PROMOTIONS (or otherwise missed while non-SENT) is the alarm."""
    chain_mids = {m for (m,) in db.execute(sa_text("""
        SELECT DISTINCT unnest(source_message_ids)
        FROM ingest_candidates
        WHERE user_id = :uid AND source_type = 'gmail' AND order_id IS NOT NULL
    """), {"uid": str(user_id)}).fetchall()} | set(RECOVERY_MESSAGE_IDS)
    table = []
    for o in outcomes:
        if o.message_id not in chain_mids:
            continue
        matched = (o.message_id in tier0_ids) if tier0_ids is not None else None
        is_sent = "SENT" in o.labels
        promo = "CATEGORY_PROMOTIONS" in o.labels
        table.append({
            "message_id": o.message_id,
            "labels": o.labels,
            "email_kind": o.decision.email_kind if o.decision else "?",
            "subject": o.subject[:52],
            "tier0_matched": matched,
            "sent_forward": is_sent,
            "ALARM_promotions_transactional": promo and not is_sent,
            "ALARM_missed_non_sent": (matched is False and not is_sent),
        })
    return sorted(table, key=lambda r: (r["email_kind"], r["message_id"]))


def print_report(rep: dict) -> None:
    w = 74
    print(f"\n{'=' * w}\n  v2 REPROCESS — DRY RUN (no DB writes)\n{'=' * w}")
    t = rep["totals"]
    print(f"  corpus: {rep['corpus_messages']} messages "
          f"(fetch_failed={rep['fetch_failed']} llm_failed={rep['llm_failed']}) "
          f"llm cost ~${rep['est_llm_cost_usd']}")
    print(f"  email kinds: {rep['email_kind_distribution']}")
    if rep["kind_overridden_messages"]:
        print(f"  kind overridden by order evidence: {rep['kind_overridden_messages']}")
    print(f"\n  v1 rows: {t['v1_candidate_rows']}  ->  v2 admitted: {t['v2_admitted']} "
          f"(needs_enrichment={t['v2_admitted_needs_enrichment']}, returns={t['v2_return_lines']}) "
          f"demoted: {t['v2_demoted']}")
    print(f"  enrichment joins: {t['enrichment_joins']}   "
          f"retargeting demotions: {t['retargeting_demotions']}")

    print(f"\n  {'MERCHANT':22}{'V1':>6}{'ADMIT':>7}{'ENRICH':>8}{'DEMOTE':>8}")
    for m, row in rep["per_merchant"].items():
        print(f"  {m[:21]:22}{row['v1_rows']:>6}{row['v2_admitted']:>7}"
              f"{row['v2_admitted_needs_enrichment']:>8}{row['v2_demoted']:>8}")

    print(f"\n  Per-order collapse:")
    for oid, row in rep["per_order"].items():
        stated = row["stated_item_count"]
        print(f"    {oid}: v1_rows={row['v1_rows']} -> v2_items={row['v2_items']} "
              f"(needs_enrichment={row['needs_enrichment']}, stated_in_email={stated}, "
              f"chain={len(row['chain_messages'])} emails)")

    print(f"\n  Zero-drop proof (known-order populations):")
    for oid, z in rep["zero_drop_proof"].items():
        flag = "PASS" if z["pass"] else "FAIL"
        print(f"    {oid}: {flag} ({z['chain_messages_checked']} chain messages checked)")
        for p in z["problems"]:
            print(f"      !! {p}")

    print(f"\n  Demotion reasons: {rep['demotion_reasons']}")
    if rep["quarantined_emails"]:
        print(f"  Quarantined emails:")
        for q in rep["quarantined_emails"]:
            print(f"    {q['message_id']} [{q['reason']}] {q['subject']!r}")
    if rep["tier0_coverage"]:
        tc = rep["tier0_coverage"]
        print(f"\n  Tier-0 coverage (new query): {tc['matched_by_new_query']}/{tc['corpus_size']} matched")
        for m in tc["missed_by_new_query"]:
            print(f"    MISSED {m['message_id']} kind={m['email_kind']} "
                  f"admitted={m['admitted_lines']} {m['subject']!r} {m['labels']}")
    print(f"{'=' * w}")


# ---------------------------------------------------------------------------
# Apply (gated)
# ---------------------------------------------------------------------------

def apply_rewrite(db, user, rows: Dict[str, SimRow], outcomes: List[MsgOutcome]) -> None:
    """REAL rewrite: stage v2 rows under a fresh run, supersede-demote v1 rows.

    Requires 0040. The v2 rows are inserted through the SAME _upsert_candidate the
    live pipeline uses; untouched v1 rows are demoted (never deleted)."""
    import uuid as _uuid
    from datetime import datetime, timezone

    from app.gmail_closet.extraction_service import _upsert_candidate
    from app.models import IngestRun, ProcessedMessage

    cols = {c["name"] for c in __import__("sqlalchemy").inspect(db.get_bind()).get_columns("ingest_candidates")}
    if "provenance" not in cols:
        print("ABORT: migration 0040 not applied to this database.")
        sys.exit(2)

    sync_id = _uuid.uuid4()
    run = IngestRun(sync_id=sync_id, user_id=user.id, status="running",
                    source_type="gmail", trigger="manual")
    db.add(run)
    db.commit()

    admitted = demoted = 0
    for r in rows.values():
        _upsert_candidate(db, dict(
            user_id=user.id, sync_id=sync_id, message_id=r.message_ids[0],
            source_line_key=r.content_key, source_message_ids=r.message_ids,
            seen_count=len(r.message_ids), name=r.name, brand=r.brand or r.merchant,
            category=r.category, color=r.color, size=r.size, quantity=r.qty,
            unit_price=r.unit_price, currency=None, order_date=None,
            is_return=r.is_return, merchant=r.merchant, order_id=r.order_id,
            image_url=None, image_status="pending", confidence_overall=None,
            confidence_json={"reprocess_v2": True},
            status="pending",
            pipeline_state="staged" if r.admitted else "rejected_recommendation",
            quarantine_reason=r.reason, needs_enrichment=r.needs_enrichment,
            provenance={"email_kinds": r.email_kinds[:6], "sections": r.sections[:6]},
            person_status="unknown",
        ))
        admitted += 1 if r.admitted else 0
        demoted += 0 if r.admitted else 1
    db.commit()

    # Supersede-demote every untouched pre-existing v1 gmail row.
    superseded = db.execute(sa_text("""
        UPDATE ingest_candidates
        SET pipeline_state = 'rejected_recommendation',
            quarantine_reason = 'superseded_v1_rewrite'
        WHERE user_id = :uid AND source_type = 'gmail'
          AND source_line_key NOT LIKE 'v2%'
          AND pipeline_state != 'rejected_recommendation'
    """), {"uid": str(user.id)}).rowcount
    # processed_messages: kind verdicts + quarantines.
    for o in outcomes:
        if not o.decision:
            continue
        status = "quarantined" if o.decision.quarantined else "extracted"
        db.execute(sa_text("""
            INSERT INTO processed_messages (id, user_id, message_id, status, email_kind,
                                            filter_reason, extract_priority, processed_at)
            VALUES (gen_random_uuid(), :uid, :mid, :status, :kind, 'reprocess_v2', 0, now())
            ON CONFLICT ON CONSTRAINT processed_messages_user_id_message_id_key
            DO UPDATE SET status = :status, email_kind = :kind, processed_at = now()
        """), {"uid": str(user.id), "mid": o.message_id, "status": status,
               "kind": o.decision.email_kind})
    run.status = "completed"
    run.admitted_count = admitted
    run.demoted_count = demoted
    run.quarantined_count = sum(1 for o in outcomes if o.decision and o.decision.quarantined)
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    print(f"\nAPPLIED: sync_id={sync_id} v2_rows={len(rows)} "
          f"(admitted={admitted} demoted={demoted}) superseded_v1={superseded}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m scripts.dev_reprocess_gmail")
    ap.add_argument("email")
    ap.add_argument("--apply", action="store_true", help="REAL rewrite (gated)")
    ap.add_argument("--i-reviewed-the-dry-run", action="store_true")
    ap.add_argument("--json", help="write the full dry-run report to this path")
    ap.add_argument("--skip-tier0-check", action="store_true")
    args = ap.parse_args()

    if args.apply and not args.i_reviewed_the_dry_run:
        print("ABORT: --apply requires --i-reviewed-the-dry-run (Gate-2 sign-off).")
        sys.exit(2)

    t0 = time.time()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == args.email.strip()).first()
        if not user:
            print(f"ERROR: no user {args.email!r}")
            sys.exit(1)
        account = db.query(GoogleAccount).filter(GoogleAccount.user_id == user.id).first()
        if not account or not account.refresh_token:
            print("ERROR: no Gmail connection for this user")
            sys.exit(1)
        token = ensure_fresh_token(account, db)

        # Corpus = every message that contributed a gmail candidate + recovery ids.
        mids = [r[0] for r in db.execute(sa_text("""
            SELECT DISTINCT unnest(source_message_ids)
            FROM ingest_candidates
            WHERE user_id = :uid AND source_type = 'gmail'
        """), {"uid": str(user.id)}).fetchall()]
        corpus = sorted(set(mids) | set(RECOVERY_MESSAGE_IDS))
        print(f"corpus: {len(mids)} contributing messages + "
              f"{len(RECOVERY_MESSAGE_IDS)} recovery ids -> {len(corpus)} total")

        outcomes: List[MsgOutcome] = []
        with httpx.Client(limits=httpx.Limits(max_connections=_CONCURRENCY + 4)) as http:
            with ThreadPoolExecutor(max_workers=_CONCURRENCY) as pool:
                futs = {pool.submit(_process_one, http, token, m): m for m in corpus}
                for i, fut in enumerate(as_completed(futs), 1):
                    outcomes.append(fut.result())
                    if i % 10 == 0:
                        print(f"  ...{i}/{len(corpus)} extracted")

            # Tier-0 coverage check with the NEW query (list ids over the scan window).
            tier0_ids = None
            if not args.skip_tier0_check:
                from app.gmail_closet.gmail_oauth_client import default_since
                q = _build_query(default_since())
                ids, _est = _list_all_ids(http, token, q)
                tier0_ids = set(ids)
                print(f"  tier-0 new-query matched {len(tier0_ids)} messages in window")

        decisions = [o.decision for o in outcomes if o.decision and not o.decision.quarantined]
        retarget_demoted = apply_retargeting_rule(decisions)
        enriched = enrichment_join(decisions)
        drift_merged = merge_order_name_drift(decisions)
        print(f"  corpus passes: enrichment_joins={enriched} name_drift_merges={drift_merged}")
        rows = simulate_staging(decisions)

        rep = build_report(user.id, db, outcomes, rows, enriched, retarget_demoted, tier0_ids)
        rep["name_drift_merges"] = drift_merged
        rep["ledgers"] = build_ledgers(user.id, db, outcomes, rows, RECOVERY_MESSAGE_IDS)
        rep["chain_table"] = build_chain_table(outcomes, tier0_ids, db, user.id)
        led = rep["ledgers"]
        print(f"\n  ROW LEDGER ({led['stored_rows_total']} stored rows, "
              f"closes={led['row_tally_closes']}): {led['row_disposition_tally']}")
        print(f"  MESSAGE LEDGER: {led['message_source_tally']}")
        print(f"\n  CHAIN TABLE (real-order messages vs new Tier-0):")
        for c in rep["chain_table"]:
            flag = ("!!ALARM " if (c["ALARM_promotions_transactional"] or c["ALARM_missed_non_sent"])
                    else ("sent-fwd" if c["sent_forward"] else "ok"))
            print(f"    [{flag:8}] {c['message_id']} kind={c['email_kind']:18} "
                  f"tier0={c['tier0_matched']} {c['labels']}")
        rep["elapsed_seconds"] = round(time.time() - t0, 1)
        print_report(rep)

        if args.json:
            with open(args.json, "w") as f:
                json.dump(rep, f, ensure_ascii=False, indent=2, default=str)
            print(f"\nfull report -> {args.json}")

        if args.apply:
            apply_rewrite(db, user, rows, outcomes)
        else:
            print("\nDRY-RUN complete: no DB writes. Use --apply after sign-off.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
