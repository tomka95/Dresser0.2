"""Product ingest pipeline (Wave F1b): one product URL -> a catalog row + embedding.

fetch (guarded, open profile) -> extract (LLM, structured) -> gate on is_clothing ->
resolve+verify image (og:image, guarded, vision-verify) -> sanitize + normalize ->
upsert into products (dedup on canonical_url) -> embed into product_embeddings.

Reusable by the dev harness now and the nightly discovery job later. Every fetch is
budget-capped; the 'open' profile keeps every SSRF guard EXCEPT the retailer allow-list
(product hosts are open-web). image_url is set ONLY on a vision-verify PASS, and only
ever to the page's first-party og:image — never a SERP/gstatic thumbnail.

Blob-copy persistence (mirroring image_blobs) is intentionally deferred: F1b records the
verified first-party image URL. Storing our own copy is a later hardening step.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.services.enrichment import normalize_category
from app.services.product_embeddings import embed_product

from .image_guard import FetchBudget, GuardRejection, guarded_fetch
from .image_resolver import extract_og_image
from .image_verify import VerifyBudget, verify_image
from .product_extraction_schema import (
    ProductExtraction,
    clamp_int,
    normalize_currency,
    sanitize_hex,
    sanitize_str_list,
    sanitize_text,
    NAME_MAX_LEN,
)
from .product_extractor import extract_product

logger = logging.getLogger(__name__)


@dataclass
class IngestProductResult:
    """Outcome of ingesting one product URL (best-effort; never raises out)."""
    url: str
    ok: bool = False
    reason: str = ""                    # why it was skipped, if ok is False
    product_id: Optional[str] = None
    is_clothing: Optional[bool] = None
    extraction: Optional[ProductExtraction] = None
    image_verified: bool = False
    image_url: Optional[str] = None
    embedded: bool = False
    escalated: bool = False
    cost_usd: float = 0.0
    notes: list = field(default_factory=list)


def _resolve_and_verify_image(
    client: httpx.Client,
    *,
    page_html: str,
    product_url: str,
    ext: ProductExtraction,
    fetch_budget: FetchBudget,
    verify_budget: VerifyBudget,
    result: IngestProductResult,
) -> Optional[str]:
    """og:image -> guarded_fetch(open) -> vision-verify. Returns the verified first-party
    image URL on a PASS, else None. Never a SERP/gstatic thumbnail (og:image only)."""
    og_url = extract_og_image(page_html, product_url)
    if not og_url:
        result.notes.append("no og:image on page")
        return None
    try:
        fetched = guarded_fetch(client, og_url, kind="image", profile="open", fetch_budget=fetch_budget)
    except GuardRejection as exc:
        result.notes.append(f"image fetch rejected ({exc.reason})")
        return None
    verdict = verify_image(
        image_bytes=fetched.content,
        content_type=fetched.content_type,
        category=ext.category.value if ext.category else None,
        color=ext.color_primary,
        name=ext.name,
        budget=verify_budget,
    )
    result.image_verified = bool(verdict.matches)
    if verdict.skipped:
        result.notes.append("image verify skipped (disabled/budget/error)")
        return None
    if not verdict.matches:
        result.notes.append(f"image verify failed (score={verdict.score:.2f})")
        return None
    return og_url


def _build_attributes_json(ext: ProductExtraction, *, source: str, model: str) -> Dict[str, Any]:
    """Per-field confidence + provenance carrier (PII-free)."""
    conf = ext.confidence.model_dump(exclude_none=True) if ext.confidence else {}
    return {
        "provenance": f"{source}_extraction",
        "source_model": model,
        "overall_confidence": ext.overall_confidence,
        "confidence": conf,
    }


def _upsert_product(db, values: Dict[str, Any]):
    """Insert or update by canonical_url (the dedup identity). Returns the Product."""
    from app.models import Product

    canonical = values.get("canonical_url")
    existing = None
    if canonical:
        existing = db.query(Product).filter(Product.canonical_url == canonical).one_or_none()
    if existing is None:
        product = Product(**values)
        db.add(product)
        db.flush()
        return product
    # Refresh attributes + freshness in place (resolve-once-serve-many).
    for k, v in values.items():
        if k in ("first_seen_at",):     # never rewind first_seen
            continue
        setattr(existing, k, v)
    db.flush()
    return existing


def ingest_product_from_url(
    db,
    url: str,
    *,
    client: Optional[httpx.Client] = None,
    fetch_budget: Optional[FetchBudget] = None,
    verify_budget: Optional[VerifyBudget] = None,
    source: str = "manual",
    geo_markets: Optional[list] = None,
) -> IngestProductResult:
    """Ingest one product URL end-to-end. Commits on success; best-effort, never raises."""
    from app.gmail_closet.product_extraction_schema import ATTR_MAX_LEN

    result = IngestProductResult(url=url)
    fetch_budget = fetch_budget or FetchBudget(settings.GMAIL_FETCH_MAX_PER_RUN)
    verify_budget = verify_budget or VerifyBudget(settings.GMAIL_VERIFY_MAX_PER_RUN)
    own_client = client is None
    client = client or httpx.Client(timeout=20.0)

    try:
        # 1) fetch the product page (open profile: every SSRF guard except allow-list).
        try:
            fetched = guarded_fetch(client, url, kind="html", profile="open", fetch_budget=fetch_budget)
        except GuardRejection as exc:
            result.reason = f"page fetch rejected ({exc.reason})"
            return result
        html = fetched.content.decode("utf-8", errors="replace")

        # 2) extract.
        outcome = extract_product(product_url=url, html=html, merchant=None)
        result.escalated = outcome.escalated
        result.cost_usd = outcome.est_cost_realistic
        ext = outcome.product
        if ext is None:
            result.reason = "api_failed" if outcome.api_failed else "parse_failed"
            return result
        result.extraction = ext
        result.is_clothing = ext.is_clothing

        # 3) garment gate.
        if not ext.is_clothing:
            result.reason = "not_clothing"
            return result

        # 4) image resolve + vision-verify (image_url set ONLY on pass).
        image_url = _resolve_and_verify_image(
            client, page_html=html, product_url=url, ext=ext,
            fetch_budget=fetch_budget, verify_budget=verify_budget, result=result,
        )
        result.image_url = image_url

        # 5) sanitize + normalize into a catalog row.
        canonical = sanitize_text(ext.canonical_url, max_len=NAME_MAX_LEN) or url
        category = normalize_category(ext.category.value) if ext.category else None
        values: Dict[str, Any] = {
            "source": source,
            "merchant": sanitize_text(ext.merchant),
            "brand": sanitize_text(ext.brand),
            "name": sanitize_text(ext.name, max_len=NAME_MAX_LEN) or "(unnamed)",
            "canonical_url": canonical,
            "product_url": url,
            "image_url": image_url,
            "price": ext.price if (ext.price is not None and ext.price >= 0) else None,
            "currency": normalize_currency(ext.currency),
            "category": category,
            "subcategory": sanitize_text(ext.subcategory),
            "color_primary": sanitize_text(ext.color_primary),
            "color_primary_hex": sanitize_hex(ext.color_primary_hex),
            "color_secondary": sanitize_text(ext.color_secondary),
            "pattern": sanitize_text(ext.pattern),
            "material": sanitize_text(ext.material),
            "fit_silhouette": sanitize_text(ext.fit_silhouette),
            "formality": clamp_int(ext.formality, 1, 5),
            "warmth": clamp_int(ext.warmth, 1, 3),
            "seasons": sanitize_str_list(ext.seasons) or None,
            "occasions": sanitize_str_list(ext.occasions) or None,
            "geo_markets": sanitize_str_list(geo_markets) or None,
            "in_stock": ext.in_stock,
            "attributes_json": _build_attributes_json(ext, source=source, model=outcome.model),
        }
        product = _upsert_product(db, values)
        result.product_id = str(product.id)

        # 6) embed into the item_embeddings space.
        result.embedded = embed_product(db, product)

        db.commit()
        result.ok = True
        return result
    except Exception as exc:
        logger.warning("ingest_product url-host=%s: error %s: %s",
                       url.split("/")[2] if "/" in url else "?", type(exc).__name__, exc)
        try:
            db.rollback()
        except Exception:
            pass
        result.reason = f"error:{type(exc).__name__}"
        return result
    finally:
        if own_client:
            client.close()
