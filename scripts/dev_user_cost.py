"""Dev cost readout: what has a user cost us (total + per sync), broken out by tier.

Usage (from project root):
    python -m scripts.dev_user_cost <email>          # one user
    python -m scripts.dev_user_cost --all            # every user, ranked by total cost
    python -m scripts.dev_user_cost <email> --json    # machine-readable

Reads the per-sync cost columns recorded on ingest_runs (Feature B) and rolls them up
per user via app.platform.usage.get_user_cost_summary. Counts + dollars only — no
email content is ever stored or shown.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import List, Tuple

from app.db import SessionLocal
from app.platform.usage import get_user_cost_summary
from app.models import IngestRun, User


def _money(v: float) -> str:
    return f"${v:,.4f}"


def _print_user(email: str, summary: dict, show_runs: bool = True) -> None:
    t = summary["totals"]
    print(f"\n{'=' * 64}")
    print(f"  {email}   ({summary['user_id']})")
    print(f"{'=' * 64}")
    print(f"  syncs:                  {t['runs']}")
    print(f"  TOTAL cost:             {_money(t['cost_usd'])}")
    print(f"    extraction (gemini):  {_money(t['extract_cost_usd'])}"
          f"   ({t['gemini_input_tokens']:,} in / {t['gemini_output_tokens']:,} out tok)")
    print(f"    vision-verify:        {_money(t['verify_cost_usd'])}"
          f"   ({t['verify_input_tokens']:,} in / {t['verify_output_tokens']:,} out tok)")
    print(f"    shopping search:      {_money(t['search_cost_usd'])}"
          f"   ({t['serper_credits']:,} serper credits)")

    if show_runs and summary["runs"]:
        print(f"\n  per sync:")
        print(f"    {'started':20} {'status':10} {'extract':>10} {'verify':>10} {'search':>10} {'total':>10}")
        print(f"    {'-' * 74}")
        for r in summary["runs"]:
            started = (r["started_at"] or "")[:19].replace("T", " ")
            print(f"    {started:20} {r['status']:10} "
                  f"{_money(r['extract_cost_usd']):>10} {_money(r['verify_cost_usd']):>10} "
                  f"{_money(r['search_cost_usd']):>10} {_money(r['cost_usd']):>10}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m scripts.dev_user_cost")
    parser.add_argument("email", nargs="?", help="User email (omit with --all)")
    parser.add_argument("--all", action="store_true", help="Every user, ranked by total cost.")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output.")
    args = parser.parse_args()
    if not args.all and not args.email:
        parser.error("provide an <email> or --all")

    db = SessionLocal()
    try:
        if args.all:
            # Only users that actually have a run (someone we've spent money on).
            user_ids = [
                (u.email, u.id)
                for u in (
                    db.query(User)
                    .join(IngestRun, IngestRun.user_id == User.id)
                    .distinct()
                    .all()
                )
            ]
            summaries: List[Tuple[str, dict]] = [
                (email, get_user_cost_summary(db, uid)) for email, uid in user_ids
            ]
            summaries.sort(key=lambda s: s[1]["totals"]["cost_usd"], reverse=True)

            if args.json:
                print(json.dumps([{"email": e, **s} for e, s in summaries], indent=2))
                return
            if not summaries:
                print("No users with any ingest runs yet.")
                return
            grand = sum(s["totals"]["cost_usd"] for _, s in summaries)
            for email, summary in summaries:
                _print_user(email, summary, show_runs=False)
            print(f"\n{'=' * 64}\n  GRAND TOTAL across {len(summaries)} user(s): {_money(grand)}\n{'=' * 64}")
            return

        user = db.query(User).filter(User.email == args.email.strip()).first()
        if not user:
            print(f"ERROR: no user with email {args.email!r}")
            sys.exit(1)
        summary = get_user_cost_summary(db, user.id)
        if args.json:
            print(json.dumps({"email": user.email, **summary}, indent=2))
        else:
            _print_user(user.email, summary)

    finally:
        db.close()


if __name__ == "__main__":
    main()
