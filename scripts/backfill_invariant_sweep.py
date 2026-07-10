"""Photo-seam Phase 6 — run the invariant backfill sweep against the configured DB.

USAGE (from the repo root, the venv python):
    python -m scripts.backfill_invariant_sweep             # DRY RUN (read-only)
    python -m scripts.backfill_invariant_sweep --execute   # classify, then mutate
    python -m scripts.backfill_invariant_sweep --execute --no-gmail-fill
    python -m scripts.backfill_invariant_sweep --execute --gen-budget 60 --verify-budget 300

NOTE: standalone scripts connect to the DATABASE_URL environment (the REMOTE DB in
this repo's dev setup) — that is the point: the sweep targets live rows. Dry-run
first, read the numbers, then --execute. Idempotent + resumable (invariant_checked_at
marker; attempt ledger; shared call budget).
"""
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Invariant backfill sweep (P6)")
    parser.add_argument("--execute", action="store_true", help="mutate (default: dry-run)")
    parser.add_argument("--no-gmail-fill", action="store_true", help="skip the B4 gmail fill")
    parser.add_argument("--gen-budget", type=int, default=None, help="generation-call ceiling")
    parser.add_argument("--verify-budget", type=int, default=None, help="verify-call ceiling")
    args = parser.parse_args()

    from app.core.config import settings
    from app.db import SessionLocal
    from app.gmail_closet.image_verify import VerifyBudget
    from app.photo_closet.backfill_sweep import run_sweep
    from app.services.image_generation.base import GenerationBudget

    gen_budget = GenerationBudget(args.gen_budget or settings.GENERATION_MAX_PER_RUN)
    verify_budget = VerifyBudget(args.verify_budget or settings.GMAIL_VERIFY_MAX_PER_RUN)

    db = SessionLocal()
    try:
        report = run_sweep(
            db,
            execute=args.execute,
            gen_budget=gen_budget,
            verify_budget=verify_budget,
            run_gmail_fill=not args.no_gmail_fill,
        )
    finally:
        db.close()

    print(json.dumps(asdict(report), indent=2, default=str))


if __name__ == "__main__":
    main()
