"""Dev re-verify: vision-verify images ALREADY stored on clothing_items (Wave 2b).

Usage (from project root):
    python -m scripts.dev_verify_images <email>            # verify all items with an image
    python -m scripts.dev_verify_images <email> --limit 5  # cap how many are checked
    python -m scripts.dev_verify_images <email> --dry-run  # report verdicts, write NOTHING

WHAT IT DOES
------------
For every clothing_item that has an image_url, it downloads the stored image and runs
the SAME vision-verify the resolver now uses (gemini-2.5-flash-lite, media_resolution
LOW) against the item's {category, color, name}:

  * PASS -> the image is trusted. Upserts a verified=true product_image_cache row,
    SEEDING the shared catalog from our known-good existing images.
  * FAIL -> the image does not match the item (e.g. a mis-associated banner). Nulls
    clothing_items.image_url and sets image_status='pending' so self-healing re-resolves
    it later. (Does NOT touch any cache row.)

Verdicts log category + result only — never names/bodies/bytes. --dry-run reports the
pass/fail decision and writes nothing (no DB change, no cache seed).
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from typing import List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

import httpx

from app.core.config import settings
from app.db import SessionLocal
from app.gmail_closet.image_verify import VerifyBudget, verify_image
from app.gmail_closet.product_image_cache import promote_verified
from app.models import ClothingItem, User


def _trunc(s: str, w: int) -> str:
    s = s or ""
    return s if len(s) <= w else s[: w - 1] + "…"


def _host(url: str) -> str:
    try:
        return httpx.URL(url).host or ""
    except Exception:
        return ""


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m scripts.dev_verify_images")
    parser.add_argument("email", help="User email (must exist in users)")
    parser.add_argument("--limit", type=int, default=None, help="Cap the number of items checked.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report verdicts only; do NOT demote failures or seed the cache.")
    args = parser.parse_args()
    email = args.email.strip()

    if not settings.GMAIL_VERIFY_ENABLED:
        print("ERROR: GMAIL_VERIFY_ENABLED is false — enable it (and set GEMINI_API_KEY) to verify.")
        sys.exit(1)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"ERROR: no user with email {email!r}")
            sys.exit(1)

        q = (
            db.query(ClothingItem)
            .filter(
                ClothingItem.user_id == user.id,
                ClothingItem.image_url.isnot(None),
            )
            .order_by(ClothingItem.created_at.asc())
        )
        items: List[ClothingItem] = q.all()
        if args.limit is not None:
            items = items[: args.limit]

        print(f"\nUser:    {email}")
        print(f"user_id: {user.id}")
        print(f"Items with an image to verify: {len(items)}{' (DRY RUN)' if args.dry_run else ''}\n")
        if not items:
            print("Nothing to verify — no clothing_items with an image_url.")
            return

        # Per-run cost guard, same cap the resolver uses.
        budget = VerifyBudget(settings.GMAIL_VERIFY_MAX_PER_RUN)

        counts: dict = defaultdict(int)
        rows_out: List[tuple] = []  # (name, category, verdict, score, action)

        with httpx.Client(timeout=20.0, follow_redirects=True) as http:
            for it in items:
                # Download our OWN stored image (a Supabase public URL we created).
                try:
                    resp = http.get(it.image_url)
                    if resp.status_code != 200 or not resp.content:
                        counts["fetch_error"] += 1
                        rows_out.append((it.name, it.category, "fetch_error", 0.0, "skipped"))
                        continue
                    ctype = (resp.headers.get("content-type") or "").split(";")[0].strip()
                    raw = resp.content
                except Exception:
                    counts["fetch_error"] += 1
                    rows_out.append((it.name, it.category, "fetch_error", 0.0, "skipped"))
                    continue

                verdict = verify_image(
                    image_bytes=raw, content_type=ctype,
                    category=it.category, color=it.color_primary, name=it.name,
                    budget=budget,
                )

                if verdict.skipped:
                    counts["skipped"] += 1
                    rows_out.append((it.name, it.category, "skipped", verdict.score, verdict.reason))
                    continue

                if verdict.matches:
                    counts["pass"] += 1
                    action = "seed cache" if not args.dry_run else "would seed"
                    if not args.dry_run:
                        promote_verified(
                            brand=it.brand, name=it.name, color=it.color_primary,
                            image_url=it.image_url, content_sha256=None,
                            source_tier="reverify", source_domain=_host(it.image_url),
                            verify_score=verdict.score,
                        )
                    rows_out.append((it.name, it.category, "PASS", verdict.score, action))
                else:
                    counts["fail"] += 1
                    action = "demote->pending" if not args.dry_run else "would demote"
                    if not args.dry_run:
                        it.image_url = None
                        it.image_status = "pending"
                    rows_out.append((it.name, it.category, "FAIL", verdict.score, action))

            if not args.dry_run:
                db.commit()

        # ---- per-item report -------------------------------------------------
        print(f"{'ITEM':30}{'CATEGORY':12}{'VERDICT':10}{'SCORE':8}{'ACTION'}")
        print("─" * 78)
        for name, cat, verdict, score, action in rows_out:
            print(f"{_trunc(name, 29):30}{_trunc(cat or '—', 11):12}{verdict:10}{score:<8.2f}{action}")

        # ---- summary ---------------------------------------------------------
        print("\n" + "=" * 60)
        print("  RE-VERIFY SUMMARY")
        print("=" * 60)
        print(f"  items checked:     {len(rows_out)}")
        print(f"  passed (seeded):   {counts['pass']}")
        print(f"  failed (demoted):  {counts['fail']}")
        if counts.get("skipped"):
            print(f"  skipped (budget/err): {counts['skipped']}")
        if counts.get("fetch_error"):
            print(f"  image fetch errors: {counts['fetch_error']}")
        if args.dry_run:
            print("  (DRY RUN — no rows demoted, no cache seeded)")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    finally:
        db.close()


if __name__ == "__main__":
    main()
