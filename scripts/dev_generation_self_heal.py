"""Generation self-heal hook: re-attempt 'pending_retry' product-card generations.

Usage (from project root):
    python -m scripts.dev_generation_self_heal <email>     # one user
    python -m scripts.dev_generation_self_heal --all       # every user with residue
    python -m scripts.dev_generation_self_heal <email> --limit 10

WHAT IT DOES
------------
Runs app.photo_closet.generation_service.run_generation_self_heal — the SAME sweep the
photo pipeline triggers opportunistically after a commit (generate_background's tail).
For each 'pending_retry' target (a pre-confirm photo ingest_candidate, or a confirmed
clothing_item that fell back to its raw crop) it re-generates FROM the stored crop, gates
the result on the MANDATORY vision-verify, and only then persists the product card.

This exists so a scheduler/cron has a ready per-user hook: it selects only users that
actually have residue and sweeps each one. Idempotent ('ready' rows are never touched),
budget-capped (the shared GENERATION_MAX_PER_RUN / GMAIL_VERIFY_MAX_PER_RUN budgets +
GENERATION_SELF_HEAL_MAX_ITEMS row cap — nothing new here), per-user isolated (every query
filters by user_id; user_id is resolved server-side, never trusted from input), and safe
to re-run. Output is ids + counts ONLY — never emails/PII/image bytes.
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
from app.models import ClothingItem, IngestCandidate, User
from app.photo_closet.generation_service import SelfHealStats, run_generation_self_heal


def _users_with_residue(db) -> list:
    """User ids that have at least one 'pending_retry' generation target.

    Mirrors run_generation_self_heal's own target filters so --all sweeps exactly the
    users a sweep could help (and no one else). Returns ids only — no PII."""
    cand_uids = (
        db.query(IngestCandidate.user_id)
        .filter(
            IngestCandidate.source_type == "photo",
            IngestCandidate.status == "pending",
            IngestCandidate.generation_status == "pending_retry",
            IngestCandidate.image_url.isnot(None),
            IngestCandidate.generated_image_url.is_(None),
        )
        .distinct()
    )
    item_uids = (
        db.query(ClothingItem.user_id)
        .filter(
            ClothingItem.source_type == "photo",
            ClothingItem.generation_status == "pending_retry",
            ClothingItem.image_url.isnot(None),
        )
        .distinct()
    )
    uids = {r[0] for r in cand_uids} | {r[0] for r in item_uids}
    return list(uids)


def _print_stats(uid, s: SelfHealStats) -> None:
    # ids + counts only (uid is a UUID, not PII).
    print(f"\n  user={uid}")
    print(f"    candidates seen: {s.candidates_seen}   items seen: {s.items_seen}")
    print(f"    regenerated -> ready: {s.ready}")
    print(f"    still held (pending_retry): {s.held}")
    print(f"    crop re-fetch errors: {s.download_errors}")
    if s.budget_stopped:
        print("    NOTE: a per-run budget was hit — rest left 'pending_retry' for a later run.")
    print(f"    generation cost: ${s.cost_usd:.4f}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m scripts.dev_generation_self_heal")
    parser.add_argument("email", nargs="?", help="User email (omit with --all)")
    parser.add_argument("--all", action="store_true",
                        help="Sweep EVERY user that has 'pending_retry' generation residue.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap targets per user (else GENERATION_SELF_HEAL_MAX_ITEMS).")
    args = parser.parse_args()

    if not args.all and not args.email:
        parser.error("provide an <email> or --all")

    db = SessionLocal()
    try:
        if args.all:
            uids = _users_with_residue(db)
            if not uids:
                print("No users with pending_retry generation residue.")
                return
        else:
            user = db.query(User).filter(User.email == args.email.strip()).first()
            if not user:
                print(f"ERROR: no user with email {args.email!r}")
                sys.exit(1)
            uids = [user.id]

        print(f"Generation self-heal over {len(uids)} user(s)…")

        totals = {"ready": 0, "held": 0, "cost": 0.0}
        for uid in uids:
            # exclude_sync_id is None: the CLI/cron has no "current run", so sweep all.
            s = run_generation_self_heal(uid, db, item_limit=args.limit)
            _print_stats(uid, s)
            totals["ready"] += s.ready
            totals["held"] += s.held
            totals["cost"] += s.cost_usd

        print("\n" + "=" * 56)
        print("  GENERATION SELF-HEAL SUMMARY")
        print("=" * 56)
        print(f"  users processed:          {len(uids)}")
        print(f"  regenerated -> ready:     {totals['ready']}")
        print(f"  still held:               {totals['held']}")
        print(f"  generation cost:          ${totals['cost']:.4f}")
        print("=" * 56)

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    finally:
        db.close()


if __name__ == "__main__":
    main()
