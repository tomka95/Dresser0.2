"""Shared, cross-user image-system models (image_blobs, product_image_cache).

Split out of the former monolithic app/models.py (P3.2, ARCHITECTURE_AUDIT R4).
Re-exported from app.models for backward compatibility -- see
app/models/__init__.py.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, ForeignKey, Integer, Numeric, Text, UniqueConstraint

from app.db import Base, GUID
from app.models._shared import _tstz


class ImageBlob(Base):
    """Content-addressed dedup ledger for stored images (Wave 0 of the image system).

    Keyed by sha256 of the raw image bytes -> the ONE storage URL those bytes were
    uploaded to. Before the resolver uploads resolved image bytes it consults this
    table: identical bytes (across runs AND across users) reuse the existing URL
    instead of uploading a fresh uuid4 object every run, which is what was leaking
    orphaned blobs into the bucket.

    Deliberately NOT user-scoped: this is a GLOBAL dedup/cache table (no user_id,
    no per-user RLS — the migration locks it to the owner/service connection). It
    is the seed Wave 2a's shared image cache EXTENDS (additive columns only — ref
    counts / provenance / last_seen), never replaces.
    """

    __tablename__ = "image_blobs"

    # sha256 hex digest of the image bytes (64 chars). PK = the dedup key.
    content_sha256 = Column(Text, primary_key=True)

    # Public Supabase storage URL the bytes were uploaded to.
    image_url = Column(Text, nullable=False)

    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)


class ProductImageCache(Base):
    """Shared, cross-user product-image cache (Wave 2a): resolve-once-serve-many.

    Keyed by ``cache_key`` = stable hash of normalize(brand)+normalize(name)+
    canonical(color) (see app/gmail_closet/product_image_cache.py). A row maps a
    PRODUCT IDENTITY to one stored image URL (referencing an image_blobs blob), so
    the same product resolved for one user can be served to others — the
    proprietary-catalog byproduct.

    SAFETY: only rows with ``verified = true`` are ever served (the resolver read
    tier filters on it). Wave 2a writes ONLY ``verified = false`` staging rows; a
    later wave's vision-verify is the sole thing that flips ``verified`` true. So
    until then the read tier is a guaranteed no-op and no unverified / mis-associated
    image can leak to another user.

    NOT user-scoped on purpose — this is product catalog reference data: NO user_id,
    NO message/order data ever. RLS enabled with no policy (owner/service writes;
    anon/authenticated denied), mirroring image_blobs. Wave 2b EXTENDS this table.
    """

    __tablename__ = "product_image_cache"

    __table_args__ = (
        UniqueConstraint("cache_key", name="product_image_cache_cache_key_key"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    # Deterministic product-identity key (UNIQUE). See make_cache_key().
    cache_key = Column(Text, nullable=False)

    # Normalized identity components stored for debuggability / verification (2b).
    brand = Column(Text, nullable=True)
    name_norm = Column(Text, nullable=True)
    color_norm = Column(Text, nullable=True)

    # The served image URL + a link to the content-addressed blob it points at.
    image_url = Column(Text, nullable=False)
    content_sha256 = Column(
        Text,
        ForeignKey("image_blobs.content_sha256", ondelete="SET NULL"),
        nullable=True,
    )

    # Provenance of the staged image (which resolver tier / host produced it).
    source_tier = Column(Text, nullable=True)
    source_domain = Column(Text, nullable=True)

    # Gate: only verified rows are served. Set true ONLY by Wave 2b vision-verify.
    verified = Column(Boolean, nullable=False, default=False)
    verify_score = Column(Numeric, nullable=True)

    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)
    last_served_at = Column(_tstz(), nullable=True)
    serve_count = Column(Integer, nullable=False, default=0)
