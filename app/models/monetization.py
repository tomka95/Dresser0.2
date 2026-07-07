"""Monetization substrate models (Wave F1c): outbound clicks + affiliate postbacks.

Split out of the former monolithic app/models.py (P3.2, ARCHITECTURE_AUDIT R4).
Re-exported from app.models for backward compatibility -- see
app/models/__init__.py.

STRUCTURAL BOUNDARY: this module is on the far side of the import-linter wall
from app.ranking / app.services.stylist.composer / app.services.stylist.compat
(see .importlinter). Nothing here is imported by those modules.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, Index, Numeric, Text

from app.db import Base, GUID
from app.models._shared import _tstz


class ProductClick(Base):
    """One outbound product click (Wave F1c). The row id IS the opaque click_id the
    frontend links to at /out/{click_id}; the destination is resolved server-side by
    this id only (never a client-supplied URL). PER-USER: RLS auth.uid() = user_id.

    Lives in the monetization substrate but the model is a plain record — the wrap /
    redirect / conversion logic is quarantined in app/monetization so ranking code can
    never import it. Migration: 0023_monetization.
    """

    __tablename__ = "product_clicks"

    __table_args__ = (
        Index("idx_product_clicks_user_created", "user_id", "created_at"),
        Index("idx_product_clicks_product", "product_id"),
        CheckConstraint("surface IN ('feed','search','chat','deck')", name="product_clicks_surface_check"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)   # == click_id
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # SET NULL: a purged product must not erase the click record.
    product_id = Column(GUID(), ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    surface = Column(Text, nullable=False)          # feed | search | chat | deck
    card_type = Column(Text, nullable=True)
    wrapped = Column(Boolean, nullable=False, default=False)
    network = Column(Text, nullable=True)
    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)


class AffiliateConversion(Base):
    """Affiliate-network postback (Wave F1c): order value + commission for a click.

    SERVICE-ONLY. RLS is enabled with NO policy (migration 0023), so only the
    owner/service connection can read it — anon/authenticated get nothing. It carries
    NO user_id; attribution is a click_id join done exclusively in monetization service
    code. This table must NEVER be joined in a user-facing or ranking query — payout
    data is structurally isolated from the feed ranker.
    """

    __tablename__ = "affiliate_conversions"

    __table_args__ = (
        Index("idx_affiliate_conversions_click", "click_id"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    click_id = Column(GUID(), ForeignKey("product_clicks.id", ondelete="SET NULL"), nullable=True)
    network = Column(Text, nullable=True)
    order_value = Column(Numeric, nullable=True)
    commission = Column(Numeric, nullable=True)
    status = Column(Text, nullable=True)
    reported_at = Column(_tstz(), nullable=True)
    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)
