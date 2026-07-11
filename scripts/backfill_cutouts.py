"""One-shot cutout backfill (Collage Phase 1): matte every existing active item.

Usage (from project root):
    python -m scripts.backfill_cutouts               # dry-run: counts only, writes NOTHING
    python -m scripts.backfill_cutouts --apply       # matte + store + stamp
    python -m scripts.backfill_cutouts --apply --user <email>      # one user
    python -m scripts.backfill_cutouts --apply --retry-no-matte    # re-attempt refusals
    python -m scripts.backfill_cutouts --apply --limit 10          # bounded slice

WHAT IT DOES
------------
Selects active clothing_items (archived_at IS NULL) that have never been matted
(cutout_status IS NULL — plus 'no_matte' rows when --retry-no-matte) and runs each
through the SAME per-item path the birth hook uses (item_cutout.service.matte_item):
display-gate -> download -> u2net matte -> QA gate -> store -> stamp. Local CPU,
$0, no generation API. The first matte pays the one-time session init (and the
one-time ~176MB weights download into U2NET_HOME if absent).

IDEMPOTENT + RESUMABLE: commits after EVERY item, so a kill loses at most the
in-flight matte; a re-run selects only rows still NULL (already-'ready' and
'no_matte' rows are never re-matted without the flag). Safe to run any number of
times — that is also the self-heal story for items whose birth-hook matte was
skipped (model unavailable, storage hiccup, masked card that later healed).

Prints a disposition summary (ready / no_matte / skipped / remaining) — ids and
counts only, never image bytes or URLs. There is NO in-app scheduler — run from
cron / by hand, like the enrichment backfill.
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
logger = logging.getLogger("backfill_cutouts")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="actually matte + store + stamp (default: dry-run counts)")
    parser.add_argument("--user", help="restrict to one user by email")
    parser.add_argument("--retry-no-matte", action="store_true",
                        help="also re-attempt items previously marked no_matte")
    parser.add_argument("--limit", type=int, default=None,
                        help="process at most N items this run")
    args = parser.parse_args()

    from app.db import SessionLocal
    from app.models import ClothingItem, User
    from app.services.item_cutout.service import STATUS_NO_MATTE, matte_item

    db = SessionLocal()
    try:
        q = db.query(ClothingItem).filter(ClothingItem.archived_at.is_(None))
        if args.user:
            user = db.query(User).filter(User.email == args.user).first()
            if user is None:
                logger.error("no user with email %s", args.user)
                return 2
            q = q.filter(ClothingItem.user_id == user.id)
        statuses = [None]
        if args.retry_no_matte:
            statuses.append(STATUS_NO_MATTE)
        q = q.filter(ClothingItem.cutout_status.in_(statuses) if len(statuses) > 1
                     else ClothingItem.cutout_status.is_(None))
        q = q.order_by(ClothingItem.created_at)
        if args.limit:
            q = q.limit(args.limit)
        targets = q.all()

        if not args.apply:
            logger.info("DRY-RUN: %d item(s) would be matted (--apply to run)", len(targets))
            return 0

        counts = {"ready": 0, "no_matte": 0, "skipped": 0}
        for item in targets:
            outcome = matte_item(db, item)
            counts[outcome] += 1
            db.commit()  # per item: resumable — a kill loses at most one matte
            logger.info("item=%s -> %s", item.id, outcome)

        remaining = (
            db.query(ClothingItem)
            .filter(ClothingItem.archived_at.is_(None),
                    ClothingItem.cutout_status.is_(None))
            .count()
        )
        logger.info(
            "DONE: processed=%d ready=%d no_matte=%d skipped=%d | still-NULL=%d",
            len(targets), counts["ready"], counts["no_matte"], counts["skipped"], remaining,
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
