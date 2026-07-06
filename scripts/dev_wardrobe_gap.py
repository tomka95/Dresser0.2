"""Dev / nightly wardrobe-gap: marginal-outfit-unlock over the shopping catalog.

Per user, computes how many wardrobe CONTEXTS (occasion × formality × warmth over the IL
climate calendar) each top-K taste candidate product newly unlocks against the closet, and
upserts user_wardrobe_gap. Pure CPU — $0 API, no LLM (reuses the same assemble_from_pool the
chat stylist composes with).

Usage (from project root):
    python -m scripts.dev_wardrobe_gap <email>       # one user
    python -m scripts.dev_wardrobe_gap --all         # every user with a closet item
"""
from __future__ import annotations

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logging.getLogger("httpx").setLevel(logging.WARNING)

from app.core.config import settings
from app.db import SessionLocal
from app.models import ClothingItem, User
from app.ranking.job import WardrobeGapStats, run_wardrobe_gap
from app.ranking.types import RankingConfig


def _print_stats(email: str, s: WardrobeGapStats) -> None:
    print(f"\n  {email}")
    print(f"    closet items:            {s.closet_items}")
    print(f"    candidates scored:       {s.candidates_scored}")
    print(f"    rows written / deleted:  {s.rows_written} / {s.rows_deleted}")
    print(f"    total unlocks / max:     {s.total_unlocks} / {s.max_unlock}")
    print(f"    cost: ${s.cost_usd:.5f}    elapsed: {s.elapsed:.2f}s")
    if s.error:
        print(f"    NOTE: run errored ({s.error}) — left as-is, rolled back.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m scripts.dev_wardrobe_gap")
    parser.add_argument("email", nargs="?", help="User email (omit with --all)")
    parser.add_argument("--all", action="store_true",
                        help="Run for EVERY user that owns at least one closet item.")
    args = parser.parse_args()

    if not args.all and not args.email:
        parser.error("provide an <email> or --all")

    cfg = RankingConfig.from_settings(settings)
    db = SessionLocal()
    try:
        if args.all:
            uids = {u for (u,) in db.query(ClothingItem.user_id).distinct()}
            if not uids:
                print("No users with closet items found.")
                return
            emails = dict(db.query(User.id, User.email).filter(User.id.in_(uids)).all())
            user_ids = [(emails.get(u, str(u)), u) for u in uids]
        else:
            user = db.query(User).filter(User.email == args.email.strip()).first()
            if not user:
                print(f"ERROR: no user with email {args.email!r}")
                sys.exit(1)
            user_ids = [(user.email, user.id)]

        print(f"Wardrobe-gap over {len(user_ids)} user(s)"
              f" (top-{cfg.gap_candidate_k} candidates, top-{cfg.gap_slot_top_m}/slot)…")

        totals = {"written": 0, "deleted": 0, "unlocks": 0, "errors": 0}
        for email, uid in user_ids:
            s = run_wardrobe_gap(db, uid, cfg=cfg)
            if s.error:
                db.rollback()   # discard the failed user's partial writes
                totals["errors"] += 1
            else:
                db.commit()     # COMMIT PER USER — isolates one user's failure from the batch
            _print_stats(email, s)
            totals["written"] += s.rows_written
            totals["deleted"] += s.rows_deleted
            totals["unlocks"] += s.total_unlocks

        print("\n" + "=" * 56)
        print("  WARDROBE-GAP SUMMARY")
        print("=" * 56)
        print(f"  users processed:   {len(user_ids)}")
        print(f"  rows written:      {totals['written']}")
        print(f"  rows deleted:      {totals['deleted']}")
        print(f"  total unlocks:     {totals['unlocks']}")
        print(f"  errored users:     {totals['errors']}")
        print(f"  total API cost:    $0.00000  (pure CPU, no LLM)")
        print("=" * 56)

    except KeyboardInterrupt:
        print("\nInterrupted.")
        db.rollback()
        sys.exit(130)
    finally:
        db.close()


if __name__ == "__main__":
    main()
