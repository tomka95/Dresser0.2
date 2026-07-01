"""Dev self-heal: drive the Phase-4 background image fill on demand.

Usage (from project root):
    python -m scripts.dev_self_heal <email>          # one user
    python -m scripts.dev_self_heal --all            # every user with a Gmail connection
    python -m scripts.dev_self_heal <email> --candidates-only
    python -m scripts.dev_self_heal <email> --confirmed-only
    python -m scripts.dev_self_heal <email> --limit 50

WHAT IT DOES
------------
Runs app.gmail_closet.image_fill_service.run_image_fill — the SAME worker the ingest
pipeline triggers in the background after the deck is shown. For each target (a still-
imageless swipe candidate, or a pending confirmed clothing_item) it:

  1. CACHE-FIRST: looks the product up in the shared, verified product_image_cache — an
     item another user already resolved fills instantly at ~0 cost.
  2. SLOW RESOLVE (residue only): re-fetches the source email and runs the resolver's
     slow tiers (og:image -> feed -> search), every hop SSRF-guarded + vision-verified,
     then writes image_url + image_status ('resolved' or, once exhausted, 'placeholder').

Idempotent and budget-capped (shared Verify/Fetch/Search budgets). Touches
ingest_candidates / clothing_items image_url + image_status ONLY. Safe to re-run.
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

from app.db import SessionLocal
from app.gmail_closet.image_fill_service import ImageFillStats, run_image_fill
from app.models import GoogleAccount, User


def _print_stats(email: str, s: ImageFillStats) -> None:
    print(f"\n  {email}")
    print(f"    candidates seen: {s.candidates_seen}   confirmed seen: {s.confirmed_seen}")
    print(f"    filled via cache (cross-user, ~0 cost): {s.cache_filled}")
    print(f"    filled via slow tiers (og/feed/search): {s.slow_filled}")
    if s.tier_counts:
        tiers = ", ".join(f"{k}={v}" for k, v in sorted(s.tier_counts.items()))
        print(f"      by tier: {tiers}")
    print(f"    exhausted -> placeholder: {s.exhausted}")
    print(f"    email re-fetch errors (left pending): {s.fetch_errors}")
    if s.budget_stopped:
        print("    NOTE: a per-run budget was hit — rest left 'pending' for a later run.")
    print(f"    elapsed: {s.elapsed:.1f}s")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m scripts.dev_self_heal")
    parser.add_argument("email", nargs="?", help="User email (omit with --all)")
    parser.add_argument("--all", action="store_true",
                        help="Self-heal EVERY user that has a Gmail connection.")
    parser.add_argument("--candidates-only", action="store_true",
                        help="Only fill still-imageless swipe candidates.")
    parser.add_argument("--confirmed-only", action="store_true",
                        help="Only self-heal pending confirmed clothing_items.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap targets per group per user (else the configured caps).")
    args = parser.parse_args()

    if not args.all and not args.email:
        parser.error("provide an <email> or --all")
    if args.candidates_only and args.confirmed_only:
        parser.error("--candidates-only and --confirmed-only are mutually exclusive")

    include_candidates = not args.confirmed_only
    include_confirmed = not args.candidates_only

    db = SessionLocal()
    try:
        if args.all:
            user_ids = [
                (u.email, u.id)
                for u in (
                    db.query(User)
                    .join(GoogleAccount, GoogleAccount.user_id == User.id)
                    .filter(GoogleAccount.refresh_token.isnot(None))
                    .all()
                )
            ]
            if not user_ids:
                print("No users with a Gmail connection found.")
                return
        else:
            user = db.query(User).filter(User.email == args.email.strip()).first()
            if not user:
                print(f"ERROR: no user with email {args.email!r}")
                sys.exit(1)
            user_ids = [(user.email, user.id)]

        print(f"Self-heal over {len(user_ids)} user(s)"
              f"{'' if include_candidates and include_confirmed else ' (scoped)'}…")

        totals = {"cache": 0, "slow": 0, "exhausted": 0}
        for email, uid in user_ids:
            s = run_image_fill(
                uid, db,
                include_candidates=include_candidates,
                include_confirmed=include_confirmed,
                candidate_limit=args.limit,
                confirmed_limit=args.limit,
            )
            _print_stats(email, s)
            totals["cache"] += s.cache_filled
            totals["slow"] += s.slow_filled
            totals["exhausted"] += s.exhausted

        print("\n" + "=" * 56)
        print("  SELF-HEAL SUMMARY")
        print("=" * 56)
        print(f"  users processed:        {len(user_ids)}")
        print(f"  filled via cache:       {totals['cache']}")
        print(f"  filled via slow tiers:  {totals['slow']}")
        print(f"  exhausted->placeholder: {totals['exhausted']}")
        print("=" * 56)

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    finally:
        db.close()


if __name__ == "__main__":
    main()
