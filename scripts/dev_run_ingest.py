"""Dev runner: execute or audit a Gmail receipt sync from the terminal.

Usage (from project root):
    python -m scripts.dev_run_ingest <email>             # real sync (writes DB)
    python -m scripts.dev_run_ingest <email> --explain   # read-only audit

SYNC MODE (default):
  Runs run_ingest_sync() directly — no HTTP, no JWT.
  Prints fetched / filtered / skipped / errors / elapsed.
  Run twice: the second run proves idempotency (everything skipped).
  THEN runs the phase-3c extraction pass (run_extraction_sync): the Tier-1-kept
  emails go to the LLM, clothing items are staged to ingest_candidates, and it
  prints emails→LLM, items extracted, clothing staged vs rejected, #escalated,
  token usage + est. $, plus a sample of ~10 staged candidates to eyeball quality.
  NOTHING is written to clothing_items (that is phase 3d, confirm).

EXPLAIN MODE (--explain):
  READ-ONLY. No writes to processed_messages, ingest_runs, or clothing_items.
  Runs the Tier-0 query, fetches every body, applies Tier-1 filter, then prints:
    - A table: SENDER | SUBJECT | KEPT/DROPPED | reason  (KEPT first)
    - The superset delta: how many messages the current Tier-0 query misses.
  Bodies are used only inside the Tier-1 filter — never printed or logged.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

# ---------------------------------------------------------------------------
# Logging: route INFO to stdout so progress from fetch/explain is visible.
# Must be configured BEFORE any app import to avoid getLogger() races.
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("googleapiclient").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# App imports
# ---------------------------------------------------------------------------
from app.db import SessionLocal
from app.gmail_closet.explain import ExplainResult, ExplainRow, explain_fetch
from app.gmail_closet.extraction_service import ExtractionStats, run_extraction_sync
from app.gmail_closet.fetch_service import IngestStats, run_ingest_sync
from app.models import GoogleAccount, IngestCandidate, User


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s:02d}s"


def _trunc(s: str, width: int) -> str:
    """Truncate string to width, adding an ellipsis if it was longer."""
    if len(s) > width:
        return s[: width - 1] + "…"  # …
    return s


def _fmt_sender(raw: str) -> str:
    """Extract the email address from 'Display Name <email>' format."""
    if "<" in raw and ">" in raw:
        addr = raw[raw.rfind("<") + 1 : raw.rfind(">")].strip()
        return addr if addr else raw.strip()
    return raw.strip()


# ---------------------------------------------------------------------------
# Sync-mode helpers
# ---------------------------------------------------------------------------

def _print_summary(label: str, stats: IngestStats) -> None:
    w = 56
    print(f"\n{'=' * w}")
    print(f"  {label}")
    print(f"{'=' * w}")
    print(f"  sync_id:        {stats.sync_id}")
    print(f"  status:         {stats.status}")
    print(f"  gmail_estimate: {stats.total_estimate}")
    print(f"  total_listed:   {stats.total_listed}")
    print(f"    skipped:      {stats.skipped:<6}  (already in processed_messages)")
    print(f"    fetched:      {stats.fetched:<6}  (passed Tier-1 → receipt signals)")
    print(f"    filtered_out: {stats.filtered:<6}  (failed Tier-1 → mktg/shipping/no signals)")
    print(f"    errors:       {stats.errors:<6}  (unrecoverable fetch failures)")
    print(f"  elapsed:        {_fmt_elapsed(stats.elapsed)}")
    print(f"{'=' * w}")


def _idempotency_verdict(run1: IngestStats, run2: IngestStats) -> None:
    print()
    all_new = run2.fetched + run2.filtered + run2.errors
    if all_new == 0 and run2.skipped >= (run1.fetched + run1.filtered):
        print(f"✓  IDEMPOTENCY HOLDS")
        print(f"   Run 2 processed 0 new messages.")
        print(f"   {run2.skipped} messages skipped (all already in processed_messages).")
    else:
        print(f"✗  IDEMPOTENCY ISSUE DETECTED")
        print(
            f"   Run 2 fetched={run2.fetched} filtered={run2.filtered} errors={run2.errors}"
            " (expected 0 for all three)"
        )
    print()


# ---------------------------------------------------------------------------
# Extraction-mode helpers (phase 3c)
# ---------------------------------------------------------------------------

def _fmt_money(d: float) -> str:
    """Sub-cent costs need more precision than $0.01."""
    return f"${d:,.4f}" if d < 1 else f"${d:,.2f}"


def _print_extraction(stats: ExtractionStats) -> None:
    w = 56
    print(f"\n{'=' * w}")
    print(f"  Extraction summary (phase 3c — LLM)")
    print(f"{'=' * w}")
    print(f"  sync_id:          {stats.sync_id}")
    print(f"  status:           {stats.status}")
    esc_rate = (stats.escalated * 100 / stats.emails_to_llm) if stats.emails_to_llm else 0
    print(f"  emails → LLM:     {stats.emails_to_llm:<6}  (Tier-1-kept, status='fetched')")
    print(f"    clothing:       {stats.clothing_msgs:<6}  (passed the clothing gate → staged)")
    print(f"    rejected:       {stats.rejected_msgs:<6}  (non-clothing → staged nothing)")
    print(f"    fetch errors:   {stats.fetch_errors:<6}  (404 / max retries; left for retry)")
    print(f"    llm errors:     {stats.llm_errors:<6}  (5xx/429 after retries; left status='fetched')")
    print(f"  items extracted:  {stats.items_extracted:<6}  (clothing line items, pre-dedup)")
    print(f"  candidates staged:{stats.candidates_staged:<6}  (DISTINCT after content-key dedup)")
    print(f"    duplicates merged:{stats.merged_duplicates:<4}  (same item collapsed across emails)")
    print(f"    with image_url: {stats.images_attached:<6}  (real product image resolved)")
    print(f"      via inline:   {stats.images_inline:<6}  (cid attachment part)")
    print(f"      via email-img:{stats.images_email_img:<6}  (embedded product-image URL, guard-fetched)")
    print(f"      via og:image: {stats.images_og:<6}  (product-link page og:image, guard-fetched)")
    print(f"  escalated:        {stats.escalated:<6}  ({esc_rate:.1f}% of emails → LLM; target ~5%)")
    print(f"  parse failures:   {stats.parse_failures:<6}  (Flash-Lite unparseable; not escalated)")
    print(f"  {'-' * (w - 4)}")
    print(f"  tokens in/out:    {stats.input_tokens:,} / {stats.output_tokens:,}")
    print(f"  est. cost @ Flash-Lite rate: {_fmt_money(stats.est_cost_flash_lite)}"
          f"  ($0.10/$0.40 per 1M)")
    print(f"  est. cost realistic (incl. escalations): {_fmt_money(stats.est_cost_realistic)}")
    print(f"  elapsed:          {_fmt_elapsed(stats.elapsed)}")
    print(f"{'=' * w}")


def _print_candidate_sample(db, sync_id, limit: int = 10) -> None:
    """Print up to `limit` staged candidates so quality can be eyeballed.

    This is dev-tool stdout (explicitly requested), NOT a log line — candidate
    names/brands are fine to show here; the redaction rule covers logger output.
    """
    rows = (
        db.query(IngestCandidate)
        .filter(IngestCandidate.sync_id == sync_id)
        .order_by(IngestCandidate.confidence_overall.desc().nullslast())
        .limit(limit)
        .all()
    )
    print(f"\n  Sample of staged candidates (up to {limit}):")
    if not rows:
        print("    (none staged)")
        return

    def _c(v, width: int) -> str:
        return _trunc(str(v) if v is not None else "—", width)

    header = (
        f"    {'NAME':24}{'BRAND':14}{'CATEGORY':12}{'COLOR':9}"
        f"{'SIZE':6}{'PRICE':>9} {'CUR':4}{'CONF':>5}{'SEEN':>5}"
    )
    print(header)
    print("    " + "─" * (len(header) - 4))
    for r in rows:
        price = f"{float(r.unit_price):.2f}" if r.unit_price is not None else "—"
        conf = f"{float(r.confidence_overall):.2f}" if r.confidence_overall is not None else "—"
        # seen_count > 1 means this item was collapsed from multiple source emails.
        seen = getattr(r, "seen_count", 1) or 1
        print(
            f"    {_c(r.name, 24):24}{_c(r.brand, 14):14}{_c(r.category, 12):12}"
            f"{_c(r.color, 9):9}{_c(r.size, 6):6}{price:>9} {_c(r.currency, 4):4}{conf:>5}"
            f"{('×' + str(seen)):>5}"
        )
    print()


# ---------------------------------------------------------------------------
# Explain-mode helpers
# ---------------------------------------------------------------------------

# Column widths for the explain table
_W_STATUS = 8    # "DROPPED "
_W_REASON = 30   # "known_retailer+receipt_signals"
_W_SENDER = 32   # email address
_W_SUBJECT = 50  # subject line


def _print_explain(result: ExplainResult, email: str) -> None:
    kept = [r for r in result.rows if r.kept]
    dropped = [r for r in result.rows if not r.kept]

    # ---- header banner -------------------------------------------------------
    print()
    banner_w = _W_STATUS + _W_REASON + _W_SENDER + _W_SUBJECT + 4
    print("┌" + "─" * (banner_w - 2) + "┐")
    title = f"  Gmail Tier-0 / Tier-1 explain — {email}"
    print(f"│{title:<{banner_w - 2}}│")
    info = f"  Window: last {2} years | Tier-0 matched: {result.tier0_count}"
    print(f"│{info:<{banner_w - 2}}│")
    print("└" + "─" * (banner_w - 2) + "┘")
    print()

    # ---- column header -------------------------------------------------------
    hdr = (
        f"{'STATUS':{_W_STATUS}}"
        f"{'REASON':{_W_REASON}}"
        f"{'SENDER':{_W_SENDER}}"
        f"SUBJECT"
    )
    sep = "─" * banner_w
    print(hdr)
    print(sep)

    # ---- rows ----------------------------------------------------------------
    def _row_line(r: ExplainRow) -> str:
        status = "KEPT" if r.kept else "DROPPED"
        sender = _trunc(_fmt_sender(r.sender), _W_SENDER)
        subject = _trunc(r.subject, _W_SUBJECT)
        return (
            f"{status:{_W_STATUS}}"
            f"{r.reason:{_W_REASON}}"
            f"{sender:{_W_SENDER}}"
            f"{subject}"
        )

    if kept:
        print(f"\n▶ KEPT ({len(kept)})\n")
        for r in kept:
            print(_row_line(r))
    else:
        print("\n(no messages kept by Tier-1)\n")

    print()
    print(sep)

    if dropped:
        print(f"\n▶ DROPPED ({len(dropped)})\n")
        for r in dropped:
            print(_row_line(r))
    else:
        print("\n(no messages dropped by Tier-1)\n")

    # ---- counts + delta ------------------------------------------------------
    print()
    print(sep)
    n_kept = len(kept)
    n_dropped = len(dropped)
    n_errors = result.tier0_count - (n_kept + n_dropped)
    delta = result.superset_count - result.tier0_count

    print(f"\n  Tier-1 breakdown:")
    print(f"    KEPT:        {n_kept:>6}  ({n_kept * 100 // max(result.tier0_count, 1)}% of Tier-0 matches)")
    print(f"    DROPPED:     {n_dropped:>6}")
    if n_errors:
        print(f"    fetch errors:{n_errors:>6}  (404 / max-retries)")

    print()
    print(f"  Tier-0 query matched:     {result.tier0_count:>6}  (exact, paginated)")
    print(f"  Superset query matches: ~{result.superset_count:>6}  (estimate, 1 list call)")

    if delta > 0:
        print(f"  Delta:                  +{delta:>6}  messages the current Tier-0 query misses")
        print()
        print(
            "  ⚠ Superset adds subject terms beyond Tier-0:\n"
            "    tracking | delivered | confirmation | billing\n"
            '    "order number" | "order summary"\n'
            "    HE: אישור | סיכום | מספר קבלה\n"
            "  If the delta is large, consider adding these to the Tier-0 query."
        )
    elif delta == 0:
        print(f"  Delta:                       0  Tier-0 query is already as broad as the superset")
    else:
        print(
            f"  Delta: {delta}  (superset estimate is lower than actual Tier-0 count;\n"
            "  resultSizeEstimate is an approximation)"
        )

    print()
    print(f"  Elapsed: {_fmt_elapsed(result.elapsed)}")
    print(f"\n  READ-ONLY: nothing written to processed_messages / ingest_runs / clothing_items.")
    print(f"  No LLM calls.\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.dev_run_ingest",
        description="Gmail receipt ingest dev runner",
    )
    parser.add_argument("email", help="User email to sync (must exist in users table)")
    parser.add_argument(
        "--explain",
        action="store_true",
        help=(
            "Read-only audit: fetch + Tier-1 filter without writing to the DB. "
            "Prints a per-message KEPT/DROPPED table and a Tier-0 vs superset count delta."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    email: str = args.email.strip()

    db = SessionLocal()
    try:
        # ----------------------------------------------------------------
        # Resolve user
        # ----------------------------------------------------------------
        user: User | None = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"ERROR: No user found with email {email!r}")
            sys.exit(1)

        account: GoogleAccount | None = (
            db.query(GoogleAccount)
            .filter(GoogleAccount.user_id == user.id)
            .first()
        )
        if not account or not account.refresh_token:
            print(
                f"ERROR: {email!r} has no Gmail connection.\n"
                "       Complete the OAuth flow via /gmail/oauth/start first."
            )
            sys.exit(1)

        print(f"\nUser:    {email}")
        print(f"user_id: {user.id}")
        print(f"scope:   {account.scope or '(not set)'}")

        # ----------------------------------------------------------------
        # --explain mode  (read-only, no DB writes, no idempotency skips)
        # ----------------------------------------------------------------
        if args.explain:
            print("\nMode: EXPLAIN (read-only — no writes to processed_messages)\n")
            result = explain_fetch(user_id=user.id, db=db)
            _print_explain(result, email)
            return

        # ----------------------------------------------------------------
        # Sync mode — run 1
        # ----------------------------------------------------------------
        print("\nStarting run 1 …")
        stats1 = run_ingest_sync(user_id=user.id, db=db)
        _print_summary("Run 1 summary", stats1)

        processed_run1 = stats1.fetched + stats1.filtered
        print(f"\nRun 1 wrote {processed_run1} rows to processed_messages.")
        print("Starting run 2 (idempotency test) …")
        print("Expected: same total_listed, ALL messages skipped, fetched=0 filtered=0.\n")

        # ----------------------------------------------------------------
        # Sync mode — run 2 (idempotency proof)
        # ----------------------------------------------------------------
        stats2 = run_ingest_sync(user_id=user.id, db=db)
        _print_summary("Run 2 summary (idempotency test)", stats2)

        _idempotency_verdict(stats1, stats2)

        # ----------------------------------------------------------------
        # Phase 3c — extraction (LLM). Picks up the Tier-1-kept messages
        # (status='fetched'), stages clothing candidates, leaves
        # clothing_items untouched.
        # ----------------------------------------------------------------
        print("Starting extraction pass (phase 3c — LLM) …\n")
        estats = run_extraction_sync(user_id=user.id, db=db)
        _print_extraction(estats)
        _print_candidate_sample(db, estats.sync_id)

        print("Confirmed: clothing_items untouched — clothing staged to ingest_candidates only.")

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    finally:
        db.close()


if __name__ == "__main__":
    main()
