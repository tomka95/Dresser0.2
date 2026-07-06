"""Dev harness: ingest one or more product URLs into the products catalog.

Runs the full F1b pipeline per URL — guarded fetch -> LLM extract -> garment gate ->
og:image resolve + vision-verify -> sanitize/normalize -> upsert products -> embed into
product_embeddings — and prints what each step produced. For manual testing / measuring
extraction accuracy on real retailer pages.

Requires GEMINI_API_KEY (extract + verify + embed) and a reachable DB. A shared
FetchBudget / VerifyBudget caps outbound fetches + vision calls across the whole run.

Usage (from project root):
    python -m scripts.dev_ingest_product <url> [<url> ...]
    python -m scripts.dev_ingest_product --geo IL <url>
    python -m scripts.dev_ingest_product --dry-run <url>     # extract only, no DB write

--dry-run skips the DB upsert + embed (prints the extraction + verify verdict only).
Print + persist (unless --dry-run); stores nothing else.
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

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.gmail_closet.image_guard import FetchBudget  # noqa: E402
from app.gmail_closet.image_verify import VerifyBudget  # noqa: E402
from app.gmail_closet.product_ingest import ingest_product_from_url  # noqa: E402


def _print_result(r) -> None:
    host = r.url.split("/")[2] if "/" in r.url else r.url
    print("\n" + "-" * 72)
    print(f"  {host}")
    print(f"  url: {r.url}")
    if r.extraction is not None:
        e = r.extraction
        print(f"    is_clothing:  {e.is_clothing}")
        print(f"    name:         {e.name!r}")
        print(f"    brand:        {e.brand!r}   merchant: {e.merchant!r}")
        print(f"    category:     {e.category.value if e.category else None} / sub={e.subcategory!r}")
        print(f"    color:        {e.color_primary!r} ({e.color_primary_hex}) / {e.color_secondary!r}")
        print(f"    pattern/mat:  {e.pattern!r} / {e.material!r}   fit: {e.fit_silhouette!r}")
        print(f"    formality/warmth: {e.formality} / {e.warmth}")
        print(f"    seasons/occ:  {e.seasons} / {e.occasions}")
        print(f"    price:        {e.price} {e.currency}   in_stock: {e.in_stock}")
        print(f"    confidence:   overall={e.overall_confidence:.2f}  escalated={r.escalated}")
    print(f"    image_verified: {r.image_verified}   image_url: {r.image_url}")
    print(f"    embedded:     {r.embedded}")
    print(f"    product_id:   {r.product_id}")
    print(f"    cost_usd:     ${r.cost_usd:.5f}")
    if r.notes:
        print(f"    notes:        {'; '.join(r.notes)}")
    print(f"    RESULT:       {'OK' if r.ok else 'SKIP/FAIL: ' + r.reason}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m scripts.dev_ingest_product")
    parser.add_argument("urls", nargs="+", help="Product page URL(s) to ingest.")
    parser.add_argument("--geo", default=None, help="Geo market tag to stamp, e.g. IL.")
    parser.add_argument("--source", default="manual", choices=("search", "feed", "manual"))
    parser.add_argument("--dry-run", action="store_true", help="Extract + verify only; no DB write.")
    args = parser.parse_args()

    if not settings.GEMINI_API_KEY:
        print("WARNING: GEMINI_API_KEY not set — extract/verify/embed will no-op or fail.")

    geo = [args.geo] if args.geo else None
    # One shared budget across the whole run (anti-amplification + cost cap).
    fetch_budget = FetchBudget(settings.GMAIL_FETCH_MAX_PER_RUN)
    verify_budget = VerifyBudget(settings.GMAIL_VERIFY_MAX_PER_RUN)

    print("=" * 72)
    print(f"  product ingest — {len(args.urls)} url(s)  source={args.source}  "
          f"geo={args.geo or '-'}  dry_run={args.dry_run}")
    print("=" * 72)

    db = SessionLocal()
    results = []
    try:
        with httpx.Client(timeout=20.0) as client:
            for url in args.urls:
                if args.dry_run:
                    r = _dry_run(db, url, client, fetch_budget, verify_budget, geo)
                else:
                    r = ingest_product_from_url(
                        db, url, client=client, fetch_budget=fetch_budget,
                        verify_budget=verify_budget, source=args.source, geo_markets=geo,
                    )
                _print_result(r)
                results.append(r)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        db.rollback()
        sys.exit(130)
    finally:
        db.close()

    ok = sum(1 for r in results if r.ok)
    clothing = sum(1 for r in results if r.is_clothing)
    verified = sum(1 for r in results if r.image_verified)
    embedded = sum(1 for r in results if r.embedded)
    total_cost = sum(r.cost_usd for r in results)
    print("\n" + "=" * 72)
    print("  SUMMARY")
    print("=" * 72)
    print(f"  urls:            {len(results)}")
    print(f"  is_clothing:     {clothing}")
    print(f"  ingested (ok):   {ok}")
    print(f"  image_verified:  {verified}")
    print(f"  embedded:        {embedded}")
    print(f"  total cost:      ${total_cost:.5f}")
    print("=" * 72)


def _dry_run(db, url, client, fetch_budget, verify_budget, geo):
    """Extract + image-verify only (no upsert/embed) — for accuracy spot-checks."""
    from app.gmail_closet.image_guard import GuardRejection, guarded_fetch
    from app.gmail_closet.product_extractor import extract_product
    from app.gmail_closet.product_ingest import IngestProductResult, _resolve_and_verify_image

    r = IngestProductResult(url=url)
    try:
        fetched = guarded_fetch(client, url, kind="html", profile="open", fetch_budget=fetch_budget)
    except GuardRejection as exc:
        r.reason = f"page fetch rejected ({exc.reason})"
        return r
    html = fetched.content.decode("utf-8", errors="replace")
    outcome = extract_product(product_url=url, html=html, merchant=None)
    r.escalated, r.cost_usd, r.extraction = outcome.escalated, outcome.est_cost_realistic, outcome.product
    if outcome.product is None:
        r.reason = "api_failed" if outcome.api_failed else "parse_failed"
        return r
    r.is_clothing = outcome.product.is_clothing
    if outcome.product.is_clothing:
        r.image_url = _resolve_and_verify_image(
            client, page_html=html, product_url=url, ext=outcome.product,
            fetch_budget=fetch_budget, verify_budget=verify_budget, result=r,
        )
    r.ok = True
    r.reason = "dry-run"
    return r


if __name__ == "__main__":
    main()
