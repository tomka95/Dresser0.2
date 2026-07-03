"""Dev enrichment backfill: widen + embed incomplete closet items on demand.

Usage (from project root):
    python -m scripts.dev_enrich_backfill <email>          # one user
    python -m scripts.dev_enrich_backfill --all            # every user with a closet item
    python -m scripts.dev_enrich_backfill <email> --limit 50

WHAT IT DOES
------------
Runs app.services.enrichment.run_enrichment_backfill — the SAME routine the eager
post-confirm background task uses (enrich_item), just swept over a user's whole closet
instead of a specific set of new items. For each INCOMPLETE item (missing formality OR
warmth OR no current-recipe embedding) it:

  1. ENRICH (Flash-Lite, text only): infers the full Tier-1/2 schema (subcategory,
     formality, warmth, seasons, occasions, pattern/material/fit, hex, length, neckline,
     sleeve_length, heel_height) from the item's core attributes. Writes flat columns +
     attributes_json with provenance='inferred'. NEVER overwrites 'user_edited' fields.
  2. EMBED: canonical product text -> item_embeddings (text-embedding-004, 768-dim),
     upserted on (item_id, model, version).

Idempotent (a re-run finds fewer incomplete rows) and budget-capped
(ENRICHMENT_BACKFILL_MAX_ITEMS loaded, ENRICHMENT_MAX_LLM_CALLS_PER_RUN LLM calls per
user per run). This is the nightly backfill's driver; there is NO in-app scheduler, so
run it from cron / by hand.
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
logging.getLogger("httpcore").setLevel(logging.WARNING)

from app.db import SessionLocal
from app.models import ClothingItem, User
from app.services.enrichment import EnrichmentStats, run_enrichment_backfill


def _print_stats(email: str, s: EnrichmentStats) -> None:
    print(f"\n  {email}")
    print(f"    incomplete items seen: {s.seen}")
    print(f"    enriched (Tier-1/2 attributes written): {s.enriched}")
    print(f"    embedded (item_embeddings upserted):    {s.embedded}")
    print(f"    skipped (already complete / no signal): {s.skipped}")
    print(f"    errors: {s.errors}")
    if s.budget_stopped:
        print("    NOTE: per-run LLM budget hit — rest left for a later run.")
    print(f"    elapsed: {s.elapsed:.1f}s")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m scripts.dev_enrich_backfill")
    parser.add_argument("email", nargs="?", help="User email (omit with --all)")
    parser.add_argument("--all", action="store_true",
                        help="Backfill EVERY user that has at least one closet item.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap items loaded per user (else ENRICHMENT_BACKFILL_MAX_ITEMS).")
    args = parser.parse_args()

    if not args.all and not args.email:
        parser.error("provide an <email> or --all")

    db = SessionLocal()
    try:
        if args.all:
            user_ids = [
                (u.email, u.id)
                for u in (
                    db.query(User)
                    .join(ClothingItem, ClothingItem.user_id == User.id)
                    .distinct()
                    .all()
                )
            ]
            if not user_ids:
                print("No users with a closet item found.")
                return
        else:
            user = db.query(User).filter(User.email == args.email.strip()).first()
            if not user:
                print(f"ERROR: no user with email {args.email!r}")
                sys.exit(1)
            user_ids = [(user.email, user.id)]

        print(f"Enrichment backfill over {len(user_ids)} user(s)…")

        totals = {"enriched": 0, "embedded": 0, "errors": 0}
        for email, uid in user_ids:
            s = run_enrichment_backfill(uid, db, limit=args.limit)
            _print_stats(email, s)
            totals["enriched"] += s.enriched
            totals["embedded"] += s.embedded
            totals["errors"] += s.errors

        print("\n" + "=" * 56)
        print("  ENRICHMENT BACKFILL SUMMARY")
        print("=" * 56)
        print(f"  users processed: {len(user_ids)}")
        print(f"  enriched:        {totals['enriched']}")
        print(f"  embedded:        {totals['embedded']}")
        print(f"  errors:          {totals['errors']}")
        print("=" * 56)

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    finally:
        db.close()


if __name__ == "__main__":
    main()
