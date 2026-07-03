"""Item embedding seam (Wave S0, Branch B).

ONE place turns a clothing_items row into a pgvector row in item_embeddings. Called
from enrich_item (after attributes are enriched, so the canonical text carries the
enriched subcategory/pattern) — which is itself reached by every ingest source: the
eager post-confirm background task (Gmail + photo) and the manual-create task, plus
the nightly backfill sweep. Result: every item, whatever its origin, is embedded once.

WHAT WE EMBED
-------------
A canonical PRODUCT string — brand + subcategory + color + pattern + fit + material +
name — lowercased and whitespace-collapsed. This is deliberately:
  * TEXT only. gemini-embedding-001 (EMBEDDING_MODEL) is truncated via MRL to 768 dims
    (output_dimensionality) to match the vector(768) column fixed at DDL time (migration
    0018). A native image/multimodal
    embedding is a later upgrade — item_embeddings.model + version exist precisely so it
    can be added under a new row with NO migration. The vision-derived attributes
    (color/pattern/material/fit) already fold the photo's visual signal into this text.
  * PII-free. Only product attribute strings — never order ids, prices, emails, or
    image bytes (privacy constraint).

WRITE PATH
----------
UPSERT on the UNIQUE (item_id, model, version) from migration 0018, so re-embedding the
same item (nightly backfill, or a corrected attribute) refreshes the vector in place
rather than inserting a duplicate. Postgres-only (pg_insert); the SQLite dev/test path
never embeds (the vector column is a Text fallback there and enrichment is not exercised).
"""
from __future__ import annotations

import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.models import ItemEmbedding

logger = logging.getLogger(__name__)


# Fields that make up the canonical string, in priority order. subcategory falls back
# to category so an un-enriched item still embeds something categorical.
def build_canonical_text(item) -> str:
    """Product-attribute string for embedding. Empty string if the item has nothing.

    brand + subcategory(||category) + color + pattern + fit + material + name, all
    lowercased and de-duplicated on the token level is overkill — we just join the
    present, stripped parts. Carries no PII (product strings only).
    """
    subcat = getattr(item, "sub_category", None) or getattr(item, "category", None)
    parts = [
        getattr(item, "brand", None),
        subcat,
        getattr(item, "color_primary", None),
        getattr(item, "pattern", None),
        getattr(item, "fit_silhouette", None),
        getattr(item, "material", None),
        getattr(item, "name", None),
    ]
    tokens = [str(p).strip() for p in parts if p is not None and str(p).strip()]
    return " ".join(tokens).lower()


def embed_item(db, item, *, provider=None) -> bool:
    """Embed one clothing_items row into item_embeddings (upsert). Returns True on write.

    Never raises: a transient embedding failure must not break the enrichment pass that
    calls this. Returns False when there was nothing to embed or the call failed, so the
    caller can leave the item for a later backfill sweep to retry.
    """
    canonical = build_canonical_text(item)
    if not canonical:
        return False

    if provider is None:
        from app.services.ai_provider import get_ai_provider

        provider = get_ai_provider()

    model = settings.EMBEDDING_MODEL
    dim = settings.EMBEDDING_DIM
    version = settings.EMBEDDING_VERSION

    try:
        vectors = provider.embed_texts(
            [canonical],
            model=model,
            dim=dim,
            task_type=settings.EMBEDDING_TASK_TYPE_DOCUMENT,
        )
    except Exception as exc:  # network / quota / SDK error — leave for a later sweep
        # Log the full message, not just the class name: a bare "ClientError" hides
        # actionable API detail (e.g. 404 model-not-found vs 429 quota). The provider
        # message carries no API key or PII.
        logger.warning("embed_item item=%s: embed call failed (%s: %s)", item.id, type(exc).__name__, exc)
        return False

    if not vectors or not vectors[0]:
        logger.warning("embed_item item=%s: empty embedding returned", item.id)
        return False
    vector = vectors[0]
    if len(vector) != dim:
        # Width MUST match the vector(dim) column or the insert fails; guard loudly.
        logger.warning(
            "embed_item item=%s: embedding width %d != EMBEDDING_DIM %d — skipping",
            item.id, len(vector), dim,
        )
        return False

    _upsert_embedding(db, item_id=item.id, user_id=item.user_id, vector=vector,
                      model=model, dim=dim, version=version)
    return True


def _upsert_embedding(
    db, *, item_id: UUID, user_id: UUID, vector: List[float],
    model: str, dim: int, version: int,
) -> None:
    """INSERT ... ON CONFLICT (item_id, model, version) DO UPDATE the vector in place."""
    tbl = ItemEmbedding.__table__
    stmt = pg_insert(tbl).values(
        item_id=item_id,
        user_id=user_id,
        embedding=vector,
        model=model,
        dim=dim,
        version=version,
    )
    ex = stmt.excluded
    stmt = stmt.on_conflict_do_update(
        constraint="item_embeddings_item_id_model_version_key",
        set_={
            "embedding": ex.embedding,
            "user_id": ex.user_id,
            "dim": ex.dim,
            "updated_at": func.now(),
        },
    )
    db.execute(stmt)


def item_has_embedding(db, item_id: UUID) -> bool:
    """True if a CURRENT-recipe embedding row already exists for this item."""
    return (
        db.query(ItemEmbedding.id)
        .filter(
            ItemEmbedding.item_id == item_id,
            ItemEmbedding.model == settings.EMBEDDING_MODEL,
            ItemEmbedding.version == settings.EMBEDDING_VERSION,
        )
        .first()
        is not None
    )
