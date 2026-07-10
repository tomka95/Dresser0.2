"""Closet retrieval for the stylist (Wave S2 scope A): structured filter +
vector kNN, always inside the caller's tenant.

TWO retrieval modes, one entry point (:func:`search_closet_items`):

  * STRUCTURED — ORM filters over clothing_items (category / formality band /
    seasons / occasions / favorites), newest first. Runs on any dialect.
  * SEMANTIC   — when ``query_text`` is given AND we're on Postgres: embed the
    query (RETRIEVAL_QUERY — the query-side twin of the RETRIEVAL_DOCUMENT
    vectors written by enrichment) and kNN over item_embeddings with pgvector
    cosine distance (the 0019 HNSW index), pre-filtered by the same structured
    constraints. Falls back to STRUCTURED on any embed/vector failure — retrieval
    must degrade, never break the turn.

OWNED-ITEMS-ONLY GUARDRAIL (three layers):
  1. every query filters ``user_id == caller`` on BOTH clothing_items and
     item_embeddings (app level),
  2. the RLS-scoped agent session makes Postgres enforce the same predicate even
     if (1) were ever dropped,
  3. :func:`_assert_owned` re-checks every returned row before it is serialized
     toward the model — a failed check raises, never returns foreign data.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import ClothingItem, ItemEmbedding
from app.models.closet import display_image_url
from app.services.enrichment import normalize_category

logger = logging.getLogger(__name__)

# Legacy alias fold at query time so 'shoes' rows still match a 'footwear' ask.
_CATEGORY_ALIASES = {
    "footwear": ("footwear", "shoes"),
    "accessory": ("accessory", "accessories"),
}


class OwnershipViolation(RuntimeError):
    """A retrieved row did not belong to the requesting user. This must be
    impossible (three guard layers) — raising loudly beats returning it."""


def _assert_owned(items: Sequence[ClothingItem], user_id: UUID) -> None:
    for item in items:
        if item.user_id != user_id:
            raise OwnershipViolation(
                f"retrieval returned item {item.id} not owned by requester"
            )


def _category_values(categories: Optional[List[str]]) -> Optional[List[str]]:
    if not categories:
        return None
    values: List[str] = []
    for c in categories:
        canonical = normalize_category(str(c).strip().lower())
        if not canonical:
            continue
        values.extend(_CATEGORY_ALIASES.get(canonical, (canonical,)))
    return values or None


def _structured_query(
    db: Session,
    user_id: UUID,
    *,
    categories: Optional[List[str]] = None,
    formality_min: Optional[int] = None,
    formality_max: Optional[int] = None,
    season: Optional[str] = None,
    occasion: Optional[str] = None,
    favorites_only: bool = False,
):
    """The shared filtered base query. user_id filter is NON-NEGOTIABLE."""
    q = db.query(ClothingItem).filter(
        ClothingItem.user_id == user_id,          # app-level tenant guard
        ClothingItem.archived_at.is_(None),
    )
    values = _category_values(categories)
    if values:
        q = q.filter(ClothingItem.category.in_(values))
    if formality_min is not None:
        # NULL formality passes (unknown is not a violation; composer penalizes).
        q = q.filter(
            (ClothingItem.formality.is_(None)) | (ClothingItem.formality >= formality_min)
        )
    if formality_max is not None:
        q = q.filter(
            (ClothingItem.formality.is_(None)) | (ClothingItem.formality <= formality_max)
        )
    if season and db.bind is not None and db.bind.dialect.name == "postgresql":
        q = q.filter(ClothingItem.seasons.any(season.lower()))
    if occasion and db.bind is not None and db.bind.dialect.name == "postgresql":
        q = q.filter(ClothingItem.occasions.any(occasion.lower()))
    if favorites_only:
        q = q.filter(ClothingItem.is_favorite.is_(True))
    return q


def _embed_query(query_text: str) -> Optional[List[float]]:
    """Embed the search text (RETRIEVAL_QUERY). None on any failure."""
    try:
        from app.platform.ai_provider import get_ai_provider

        vectors = get_ai_provider().embed_texts(
            [query_text[:512]],
            model=settings.EMBEDDING_MODEL,
            dim=settings.EMBEDDING_DIM,
            task_type="RETRIEVAL_QUERY",
        )
        if vectors and len(vectors[0]) == settings.EMBEDDING_DIM:
            return vectors[0]
    except Exception as exc:
        logger.warning("closet search: query embed failed (%s)", type(exc).__name__)
    return None


def search_closet_items(
    db: Session,
    user_id: UUID,
    *,
    query_text: Optional[str] = None,
    categories: Optional[List[str]] = None,
    formality_min: Optional[int] = None,
    formality_max: Optional[int] = None,
    season: Optional[str] = None,
    occasion: Optional[str] = None,
    favorites_only: bool = False,
    limit: Optional[int] = None,
) -> List[ClothingItem]:
    """Retrieve a SUBSET of the caller's closet (never a full dump).

    Semantic ordering when ``query_text`` is provided (Postgres + embeddable),
    otherwise structured/newest-first. Every path re-asserts ownership.
    """
    limit = min(int(limit or settings.CHAT_RETRIEVAL_LIMIT), settings.CHAT_RETRIEVAL_LIMIT)
    filters = dict(
        categories=categories,
        formality_min=formality_min,
        formality_max=formality_max,
        season=season,
        occasion=occasion,
        favorites_only=favorites_only,
    )

    is_postgres = db.bind is not None and db.bind.dialect.name == "postgresql"
    if query_text and query_text.strip() and is_postgres:
        vector = _embed_query(query_text.strip())
        if vector is not None:
            items = _vector_search(db, user_id, vector, limit=limit, **filters)
            if items:
                _assert_owned(items, user_id)
                return items
            # fall through to structured on empty (e.g. nothing embedded yet)

    items = (
        _structured_query(db, user_id, **filters)
        .order_by(ClothingItem.created_at.desc())
        .limit(limit)
        .all()
    )
    _assert_owned(items, user_id)
    return items


def _vector_search(
    db: Session,
    user_id: UUID,
    vector: List[float],
    *,
    limit: int,
    **filters: Any,
) -> List[ClothingItem]:
    """kNN over item_embeddings (cosine), joined to the structured filters.

    BOTH tables are filtered by user_id: item_embeddings.user_id is denormalized
    exactly so this query needs no cross-tenant join, and the RLS policies on
    both relations backstop it.
    """
    distance = ItemEmbedding.embedding.cosine_distance(vector)
    q = (
        _structured_query(db, user_id, **filters)
        .join(ItemEmbedding, ItemEmbedding.item_id == ClothingItem.id)
        .filter(
            ItemEmbedding.user_id == user_id,     # app-level tenant guard (again)
            ItemEmbedding.model == settings.EMBEDDING_MODEL,
            ItemEmbedding.version == settings.EMBEDDING_VERSION,
        )
        .order_by(distance)
        .limit(limit)
    )
    return q.all()


def get_owned_items(db: Session, user_id: UUID, item_ids: Sequence[UUID]) -> List[ClothingItem]:
    """Resolve item ids -> rows, RESTRICTED to the caller's closet.

    Ids that don't exist, belong to someone else, or are archived (Photo-seam
    Phase 6b: incl. a quarantined non-clothing row) are silently absent from the
    result — the caller compares counts and fails closed. This is the single
    choke point every model-supplied item id passes through (compose_outfit and
    every other tool that resolves ids into rows).
    """
    ids = [i for i in item_ids if i is not None]
    if not ids:
        return []
    items = (
        db.query(ClothingItem)
        .filter(
            ClothingItem.user_id == user_id,
            ClothingItem.id.in_(ids),
            ClothingItem.archived_at.is_(None),
        )
        .all()
    )
    _assert_owned(items, user_id)
    return items


def serialize_item(item: ClothingItem) -> Dict[str, Any]:
    """Compact, model-facing item payload (Tier-1 attributes + image)."""
    return {
        "id": str(item.id),
        "name": item.name,
        "category": normalize_category(item.category) or item.category,
        "subCategory": item.sub_category,
        "color": item.color_primary,
        "colorHex": item.color_primary_hex,
        "pattern": item.pattern,
        "material": item.material,
        "fit": item.fit_silhouette,
        "formality": item.formality,
        "warmth": item.warmth,
        "seasons": item.seasons,
        "occasions": item.occasions,
        "brand": item.brand,
        "isFavorite": bool(item.is_favorite),
        # G6: on-model mask — never serialize a person crop to the client/LLM (outfit cards,
        # chat). Shows only a verified person-free card once generation is 'ready'.
        "imageUrl": display_image_url(item),
    }


def closet_summary(db: Session, user_id: UUID) -> Dict[str, int]:
    """Per-category counts for the system prompt (stats, never a full dump)."""
    from sqlalchemy import func

    rows = (
        db.query(ClothingItem.category, func.count(ClothingItem.id))
        .filter(ClothingItem.user_id == user_id, ClothingItem.archived_at.is_(None))
        .group_by(ClothingItem.category)
        .all()
    )
    summary: Dict[str, int] = {}
    for category, count in rows:
        key = normalize_category(category) or category or "other"
        summary[key] = summary.get(key, 0) + int(count)
    return summary
