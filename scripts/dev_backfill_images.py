"""Dev backfill: put REAL product images on closet items already in clothing_items.

Usage (from project root):
    python -m scripts.dev_backfill_images <email>            # fill items missing an image
    python -m scripts.dev_backfill_images <email> --all      # re-resolve ALL source-backed items
    python -m scripts.dev_backfill_images <email> --limit 5  # cap how many items are touched
    python -m scripts.dev_backfill_images <email> --dry-run  # resolve + report, write NOTHING

WHAT IT DOES
------------
For every clothing_item with BOTH source_message_id and source_google_account_id, it
re-fetches that Gmail message (trusted Gmail API), runs the same email-embedded image
resolver the extraction pass now uses (inline -> email-img -> og:image, every remote
hop SSRF-guarded), uploads the resolved image to Supabase storage, and sets
clothing_items.image_url. Items sharing one email are resolved TOGETHER so multi-item
receipts associate each image to the right line by DOM proximity.

It reports, per item, which tier resolved the image (inline / email-img / og:image /
none), and a per-tier summary. This touches clothing_items.image_url ONLY — it does
NOT re-run extraction, confirm, or swipe.
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from typing import Dict, List, Optional

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
from app.gmail_closet.fetch_service import _fetch_one
from app.gmail_closet.gmail_oauth_service import ensure_fresh_token
from app.gmail_closet.image_resolver import (
    ResolvedImage,
    ResolvedImageCache,
    ResolverItem,
    resolve_item_images,
)
from app.gmail_closet.image_guard import FetchBudget
from app.gmail_closet.image_verify import VerifyBudget
from app.gmail_closet.shopping_search import SearchBudget
from app.models import ClothingItem, GoogleAccount, User

_TIER_LABEL = {
    "inline": "inline (cid part)",
    "email-img": "email-img URL (guarded)",
    "og:image": "product-link og:image (guarded)",
    "none": "—",
}


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _trunc(s: str, w: int) -> str:
    s = s or ""
    return s if len(s) <= w else s[: w - 1] + "…"


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m scripts.dev_backfill_images")
    parser.add_argument("email", help="User email (must exist in users)")
    parser.add_argument("--all", action="store_true",
                        help="Re-resolve ALL source-backed items (default: only those missing an image).")
    parser.add_argument("--limit", type=int, default=None, help="Cap the number of items processed.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Resolve + report only; do NOT write image_url.")
    args = parser.parse_args()
    email = args.email.strip()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"ERROR: no user with email {email!r}")
            sys.exit(1)

        account = (
            db.query(GoogleAccount).filter(GoogleAccount.user_id == user.id).first()
        )
        if not account or not account.refresh_token:
            print(f"ERROR: {email!r} has no Gmail connection (need a refresh token to re-fetch emails).")
            sys.exit(1)

        # Source-backed closet items: both provenance columns present.
        q = (
            db.query(ClothingItem)
            .filter(
                ClothingItem.user_id == user.id,
                ClothingItem.source_message_id.isnot(None),
                ClothingItem.source_google_account_id.isnot(None),
            )
        )
        if not args.all:
            q = q.filter(ClothingItem.image_url.is_(None))
        q = q.order_by(ClothingItem.created_at.asc())
        items: List[ClothingItem] = q.all()
        if args.limit is not None:
            items = items[: args.limit]

        print(f"\nUser:    {email}")
        print(f"user_id: {user.id}")
        mode = "ALL source-backed" if args.all else "source-backed items MISSING an image"
        print(f"Scope:   {mode}{' (DRY RUN)' if args.dry_run else ''}")
        print(f"Items to backfill: {len(items)}\n")

        if not items:
            print("Nothing to backfill — no clothing_items with a source_message_id + "
                  "source_google_account_id" + ("" if args.all else " and a null image_url") + ".")
            print("(Run a sync + confirm first: python -m scripts.dev_run_ingest <email> ; "
                  "python -m scripts.dev_confirm_ingest <email>)")
            return

        # Storage: required to actually persist images. Without it we still resolve +
        # report the tier (so you can see what WOULD resolve), but write nothing.
        storage_client = None
        try:
            from app.utils.supabase_storage import SupabaseStorageClient
            storage_client = SupabaseStorageClient.from_env()
        except Exception:
            print("WARNING: Supabase storage not configured — will REPORT tiers but not store images.\n")

        token = ensure_fresh_token(account, db)
        cache = ResolvedImageCache()
        verify_budget = VerifyBudget(settings.GMAIL_VERIFY_MAX_PER_RUN)
        fetch_budget = FetchBudget(settings.GMAIL_FETCH_MAX_PER_RUN)
        search_budget = SearchBudget(settings.GMAIL_SEARCH_MAX_PER_RUN)

        # Group items by their source email so each message is fetched once and
        # multi-item receipts associate correctly.
        by_msg: Dict[str, List[ClothingItem]] = defaultdict(list)
        for it in items:
            by_msg[it.source_message_id].append(it)

        tier_counts: Dict[str, int] = defaultdict(int)
        stored_count = 0
        rows_out: List[tuple] = []  # (name, tier, detail, stored?)

        with httpx.Client(limits=httpx.Limits(max_connections=10, max_keepalive_connections=10)) as http:
            for msg_id, group in by_msg.items():
                raw = _fetch_one(http, token, msg_id)
                if raw is None:
                    for it in group:
                        tier_counts["fetch_error"] += 1
                        rows_out.append((it.name, "fetch_error", "could not re-fetch email", False))
                    continue

                payload = raw.get("payload", {})
                resolver_items = [
                    ResolverItem(
                        name=it.name,
                        unit_price=_to_float(it.unit_price),
                        color=it.color_primary,
                        size=it.size,
                        brand=it.brand,       # feeds the shared product-image cache key
                        category=it.category,  # garment type -> vision-verify gate
                    )
                    for it in group
                ]
                resolved: List[ResolvedImage] = resolve_item_images(
                    payload=payload,
                    items=resolver_items,
                    client=http,
                    token=token,
                    msg_id=msg_id,
                    storage_client=storage_client,
                    cache=cache,
                    user_id=user.id,
                    verify_budget=verify_budget,
                    fetch_budget=fetch_budget,
                    search_budget=search_budget,
                )

                for it, ri in zip(group, resolved):
                    tier_counts[ri.tier] += 1
                    did_store = False
                    if ri.stored_url and not args.dry_run:
                        it.image_url = ri.stored_url
                        it.image_status = "resolved"  # keep status in sync with the write
                        did_store = True
                        stored_count += 1
                    elif ri.stored_url and args.dry_run:
                        stored_count += 1  # would-store
                    elif not ri.stored_url and not args.dry_run and not it.image_url:
                        # All tiers exhausted with no image -> 'placeholder' so the
                        # lifecycle stays consistent with the background fill / self-heal.
                        it.image_status = "placeholder"
                    rows_out.append((it.name, ri.tier, ri.detail, did_store or bool(ri.stored_url)))

                if not args.dry_run:
                    db.commit()

        # ---- per-item report -------------------------------------------------
        print(f"{'ITEM':30}{'TIER':16}{'VIA':26}{'STORED'}")
        print("─" * 80)
        for name, tier, detail, stored in rows_out:
            print(f"{_trunc(name, 29):30}{_trunc(tier, 15):16}{_trunc(detail, 25):26}{'yes' if stored else 'no'}")

        # ---- summary ---------------------------------------------------------
        print("\n" + "=" * 60)
        print("  BACKFILL SUMMARY")
        print("=" * 60)
        total = len(rows_out)
        resolved_n = tier_counts["inline"] + tier_counts["email-img"] + tier_counts["og:image"]
        print(f"  items processed:        {total}")
        print(f"  resolved a real image:  {resolved_n}")
        print(f"    via inline (cid):     {tier_counts['inline']}")
        print(f"    via email-img URL:    {tier_counts['email-img']}")
        print(f"    via og:image:         {tier_counts['og:image']}")
        print(f"  no image found:         {tier_counts['none']}")
        if tier_counts.get("fetch_error"):
            print(f"  email re-fetch errors:  {tier_counts['fetch_error']}")
        verb = "would be stored" if args.dry_run else "stored to Supabase + written to image_url"
        print(f"  {verb}: {stored_count}")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    finally:
        db.close()


if __name__ == "__main__":
    main()
