"""Product embedding seam (Wave F1b) — the catalog twin of embeddings.embed_item.

ONE place turns a products row into a pgvector row in product_embeddings, in the
EXACT SAME vector space as item_embeddings, so cosine(product, closet-centroid) — the
taste_match signal — is meaningful. To guarantee that:

  * The canonical text uses the SAME formula as item embeddings — brand + subcategory
    (||category) + color + pattern + fit + material + name — by reusing
    embeddings.build_canonical_text through a tiny field-name adapter (products call it
    `subcategory`; clothing_items call it `sub_category`). Sharing the function means the
    recipe cannot drift between the two corpora.
  * model / dim / version come from the SAME settings.EMBEDDING_* the item path reads.
    An import-time assertion (_assert_embedding_space_parity) fails LOUD if the product
    vector column, the item vector column, and EMBEDDING_DIM ever disagree — mismatched
    dims/versions make cross-corpus cosine meaningless, so we refuse to import rather
    than silently write garbage.

Postgres-only write (pg_insert upsert on the UNIQUE (product_id, model, version)); the
SQLite dev/test path never embeds (vector column is a Text fallback there).
"""
from __future__ import annotations

import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.models import ItemEmbedding, Product, ProductEmbedding
from app.services.embeddings import build_canonical_text

logger = logging.getLogger(__name__)


class _ProductCanonicalView:
    """Adapts a Product to the attribute names build_canonical_text expects, so the
    embedding recipe is LITERALLY shared with item embeddings (no parallel formula)."""

    __slots__ = ("brand", "sub_category", "category", "color_primary",
                 "pattern", "fit_silhouette", "material", "name")

    def __init__(self, p: Product):
        self.brand = p.brand
        self.sub_category = p.subcategory      # products call it `subcategory`
        self.category = p.category
        self.color_primary = p.color_primary
        self.pattern = p.pattern
        self.fit_silhouette = p.fit_silhouette
        self.material = p.material
        self.name = p.name


def build_product_canonical_text(product: Product) -> str:
    """Canonical embedding string for a product — identical recipe to embed_item."""
    return build_canonical_text(_ProductCanonicalView(product))


def _vector_dim(model_cls) -> Optional[int]:
    """Best-effort read of a model's vector column width; None if unavailable
    (e.g. the SQLite Text fallback carries no dim)."""
    try:
        return getattr(model_cls.__table__.c.embedding.type, "dim", None)
    except Exception:
        return None


def _assert_embedding_space_parity() -> None:
    """Fail loud at import if product + item embeddings would not share a space.

    A version/dim mismatch silently corrupts every taste_match cosine, so this is a
    hard import-time gate rather than a runtime warning.
    """
    assert settings.EMBEDDING_MODEL, "EMBEDDING_MODEL must be set"
    assert isinstance(settings.EMBEDDING_DIM, int) and settings.EMBEDDING_DIM > 0, \
        "EMBEDDING_DIM must be a positive int"
    assert isinstance(settings.EMBEDDING_VERSION, int), "EMBEDDING_VERSION must be an int"

    item_dim = _vector_dim(ItemEmbedding)
    prod_dim = _vector_dim(ProductEmbedding)
    # On Postgres both resolve to the pgvector Vector(dim); they MUST agree with each
    # other and with EMBEDDING_DIM. On the SQLite fallback dim is None -> skip (no vectors).
    if item_dim is not None and prod_dim is not None:
        assert item_dim == prod_dim == settings.EMBEDDING_DIM, (
            f"embedding-space drift: item_embeddings dim={item_dim}, "
            f"product_embeddings dim={prod_dim}, EMBEDDING_DIM={settings.EMBEDDING_DIM} "
            "— product/item cosine would be meaningless; refusing to import."
        )


_assert_embedding_space_parity()


def embed_product(db, product: Product, *, provider=None) -> bool:
    """Embed one products row into product_embeddings (upsert). Returns True on write.

    Never raises: a transient embedding failure must not break the ingest pass. Uses
    the SAME model/dim/version/task_type as item embeddings (settings.EMBEDDING_*), so
    the written vector lives in the item_embeddings space.
    """
    canonical = build_product_canonical_text(product)
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
    except Exception as exc:
        logger.warning("embed_product product=%s: embed call failed (%s: %s)",
                       product.id, type(exc).__name__, exc)
        return False

    if not vectors or not vectors[0]:
        logger.warning("embed_product product=%s: empty embedding returned", product.id)
        return False
    vector = vectors[0]
    if len(vector) != dim:
        logger.warning("embed_product product=%s: embedding width %d != EMBEDDING_DIM %d — skipping",
                       product.id, len(vector), dim)
        return False

    _upsert_product_embedding(db, product_id=product.id, vector=vector,
                              model=model, dim=dim, version=version)
    return True


def _upsert_product_embedding(
    db, *, product_id: UUID, vector: List[float], model: str, dim: int, version: int,
) -> None:
    """INSERT ... ON CONFLICT (product_id, model, version) DO UPDATE the vector in place."""
    tbl = ProductEmbedding.__table__
    stmt = pg_insert(tbl).values(
        product_id=product_id,
        embedding=vector,
        model=model,
        dim=dim,
        version=version,
    )
    ex = stmt.excluded
    stmt = stmt.on_conflict_do_update(
        constraint="product_embeddings_product_id_model_version_key",
        set_={"embedding": ex.embedding, "dim": ex.dim, "updated_at": func.now()},
    )
    db.execute(stmt)


def product_has_embedding(db, product_id: UUID) -> bool:
    """True if a CURRENT-recipe embedding row already exists for this product."""
    return (
        db.query(ProductEmbedding.id)
        .filter(
            ProductEmbedding.product_id == product_id,
            ProductEmbedding.model == settings.EMBEDDING_MODEL,
            ProductEmbedding.version == settings.EMBEDDING_VERSION,
        )
        .first()
        is not None
    )
