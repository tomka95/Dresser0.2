"""Shopping-feed ranker models: shared product catalog + wardrobe-gap precompute.

Split out of the former monolithic app/models.py (P3.2, ARCHITECTURE_AUDIT R4).
Re-exported from app.models for backward compatibility -- see
app/models/__init__.py.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Column, ForeignKey, Index, Integer, Numeric, Text,
    UniqueConstraint, text,
)

from app.db import Base, GUID
from app.models._shared import _jsonb, _text_array, _tstz, _vector


class Product(Base):
    """Shared, cross-user shopping-feed catalog row (Wave F1b): one discovered
    garment product page extracted into our universal garment schema.

    NOT user-scoped on purpose — product catalog reference data: NO user_id, NO
    message/order data ever. RLS enabled with no policy (owner/service writes;
    anon/authenticated denied), mirroring product_image_cache / image_blobs.

    STRUCTURAL BOUNDARY: garment attributes + price ONLY. There is deliberately no
    affiliate id, payout, or click/redirect URL on this model — monetization lives
    in a separate module (F1c) so ranking code cannot read a payout field. Do not
    add one here. Migration: 0022_products_corpus.
    """

    __tablename__ = "products"

    __table_args__ = (
        UniqueConstraint("canonical_url", name="products_canonical_url_key"),
        Index("idx_products_active_last_seen", "active", "last_seen_at"),
        Index("idx_products_category", "category"),
        # Named CHECKs (not diffed by autogenerate; declared for parity w/ 0022).
        CheckConstraint("source IN ('search','feed','manual')", name="products_source_check"),
        CheckConstraint("formality IS NULL OR (formality >= 1 AND formality <= 5)", name="products_formality_check"),
        CheckConstraint("warmth IS NULL OR (warmth >= 1 AND warmth <= 3)", name="products_warmth_check"),
        CheckConstraint("currency IS NULL OR length(currency) = 3", name="products_currency_len_check"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    # Discovery origin. CHECK in ('search','feed','manual').
    source = Column(Text, nullable=False)
    merchant = Column(Text, nullable=True)
    brand = Column(Text, nullable=True)
    name = Column(Text, nullable=False)
    # Dedup identity (UNIQUE): the retailer's canonical product URL. product_url is
    # the page we actually fetched/extracted from.
    canonical_url = Column(Text, nullable=True)
    product_url = Column(Text, nullable=False)
    # OUR verified image URL — set ONLY after guard-fetch + vision-verify pass.
    image_url = Column(Text, nullable=True)
    price = Column(Numeric, nullable=True)
    currency = Column(Text, nullable=True)
    # Universal garment schema — SAME vocabulary as clothing_items (0018).
    category = Column(Text, nullable=True)
    subcategory = Column(Text, nullable=True)
    color_primary = Column(Text, nullable=True)
    color_primary_hex = Column(Text, nullable=True)
    color_secondary = Column(Text, nullable=True)
    pattern = Column(Text, nullable=True)
    material = Column(Text, nullable=True)
    fit_silhouette = Column(Text, nullable=True)
    formality = Column(Integer, nullable=True)   # 1..5
    warmth = Column(Integer, nullable=True)       # 1..3
    seasons = Column(_text_array(), nullable=True)
    occasions = Column(_text_array(), nullable=True)
    geo_markets = Column(_text_array(), nullable=True)
    in_stock = Column(Boolean, nullable=True)
    # Per-field confidence + provenance (same shape as clothing_items.attributes_json).
    attributes_json = Column(_jsonb(), nullable=False, default=dict)
    first_seen_at = Column(_tstz(), default=datetime.utcnow, nullable=False)
    last_seen_at = Column(_tstz(), default=datetime.utcnow, nullable=False)
    last_checked_at = Column(_tstz(), nullable=True)
    active = Column(Boolean, nullable=False, default=True)


class ProductEmbedding(Base):
    """pgvector embedding for a catalog product (Wave F1b).

    Mirror of ItemEmbedding, in the SAME vector space (gemini-embedding-001, dim 768,
    EMBEDDING_VERSION pinned identical) so cosine(product, closet-centroid) — the
    taste_match signal — is meaningful. Side table (not a column on products) so
    re-embedding / model-versioning never touches the catalog row and the ANN index
    lives on a dedicated relation. NO user_id — shared catalog. Migration 0022.
    """

    __tablename__ = "product_embeddings"

    __table_args__ = (
        UniqueConstraint("product_id", "model", "version",
                         name="product_embeddings_product_id_model_version_key"),
        # ANN index (0022) — hnsw + cosine, identical params to item_embeddings (0019).
        Index(
            "idx_product_embeddings_embedding_hnsw", "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    product_id = Column(GUID(), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    # Dimension fixed at DDL time (config.EMBEDDING_DIM). MUST match item_embeddings.
    embedding = Column(_vector(768), nullable=False)
    model = Column(Text, nullable=False)
    dim = Column(Integer, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)
    updated_at = Column(_tstz(), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class UserWardrobeGap(Base):
    """Precomputed marginal-outfit-unlock for the shopping feed (Wave F2).

    One row per (user, candidate product), written by the nightly wardrobe-gap job
    (scripts/dev_wardrobe_gap.py -> app.ranking.gap). ``unlock_count`` is how many
    wardrobe CONTEXTS (occasion × formality × warmth over the IL climate calendar) the
    product newly satisfies against what the user ALREADY owns — the marginality signal
    the ranker's ``wardrobe_gap`` term reads. ``gap_context`` carries the preview payload
    (which occasions/categories it fills + example owned-item ids). PER-USER: RLS
    auth.uid() = user_id (migration 0024).

    Pure record. The job that fills it and the ranker that reads it live in app.ranking,
    on the correct side of the import-linter wall — no payout/commission field is
    reachable from here. Monetization happens only at click time, in app/monetization.
    """

    __tablename__ = "user_wardrobe_gap"

    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="user_wardrobe_gap_user_product_key"),
        Index("idx_user_wardrobe_gap_user_unlock", "user_id", text('unlock_count DESC')),
        Index("idx_user_wardrobe_gap_user_computed", "user_id", "computed_at"),
        CheckConstraint("unlock_count >= 0", name="user_wardrobe_gap_unlock_nonneg_check"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(GUID(), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    unlock_count = Column(Integer, nullable=False, default=0)
    gap_context = Column(_jsonb(), nullable=False, default=dict)
    computed_at = Column(_tstz(), default=datetime.utcnow, nullable=False)
