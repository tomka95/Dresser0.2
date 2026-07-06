"""Monetization service (Wave F1c): mint clicks, resolve destinations, isolate payouts.

mint_click records a click (product + surface + user) and returns its opaque id.
resolve_destination looks a click up BY ID ONLY, wraps the product's own URL, records
how it resolved, fires the click_out event, and returns the outbound URL. No function
here accepts a client-supplied destination — the /out route has no open-redirect surface.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Product, ProductClick
from app.services.events_service import log_event

from .wrap import wrap_url

logger = logging.getLogger(__name__)

_SURFACES = frozenset({"feed", "search", "chat", "deck"})


class ClickValidationError(ValueError):
    """A click could not be minted (bad surface / unknown product)."""


@dataclass
class ResolvedClick:
    wrapped_url: str
    network: Optional[str]
    wrapped: bool
    user_id: UUID
    product_id: Optional[UUID]


def mint_click(
    db: Session,
    *,
    user_id: UUID,
    product_id: UUID,
    surface: str,
    card_type: Optional[str] = None,
) -> ProductClick:
    """Record a click and return it (row id == click_id). Does NOT commit.

    user_id is always the JWT subject (never client-supplied). product_id must resolve
    to a real catalog product. surface is enum-validated.
    """
    if surface not in _SURFACES:
        raise ClickValidationError(f"unknown surface: {surface!r}")
    product = db.query(Product.id).filter(Product.id == product_id).one_or_none()
    if product is None:
        raise ClickValidationError("unknown product")
    click = ProductClick(
        user_id=user_id,
        product_id=product_id,
        surface=surface,
        card_type=(str(card_type)[:64] if card_type else None),
    )
    db.add(click)
    db.flush()
    return click


def resolve_destination(db: Session, click_id: str) -> Optional[ResolvedClick]:
    """Look up a click BY ID and return its wrapped outbound URL. None if not found /
    no destination. Records the resolution + fires a click_out event, then commits.

    The destination is ALWAYS the product's own canonical/product URL from our DB —
    never anything from the request. This is the entire open-redirect defense.
    """
    try:
        cid = UUID(str(click_id))
    except (ValueError, TypeError):
        return None

    click = db.query(ProductClick).filter(ProductClick.id == cid).one_or_none()
    if click is None:
        return None

    dest: Optional[str] = None
    if click.product_id is not None:
        product = (
            db.query(Product.canonical_url, Product.product_url)
            .filter(Product.id == click.product_id)
            .one_or_none()
        )
        if product is not None:
            dest = product.canonical_url or product.product_url
    if not dest:
        return None  # product purged / no URL — nothing to redirect to

    wr = wrap_url(dest, str(click.id))
    click.wrapped = wr.wrapped
    click.network = wr.network

    # Fire the click_out interaction event (attributed to the click's own user).
    try:
        log_event(
            db,
            user_id=click.user_id,
            event_type="click_out",
            entity_type="product",
            entity_id=str(click.product_id) if click.product_id else None,
            source=click.surface,
            properties={
                "network": wr.network or "plain",
                "wrapped": wr.wrapped,
                "card_type": click.card_type,
            },
        )
    except Exception:  # telemetry must never break the redirect
        logger.warning("click_out event failed for click %s", click.id)

    db.commit()
    return ResolvedClick(
        wrapped_url=wr.url, network=wr.network, wrapped=wr.wrapped,
        user_id=click.user_id, product_id=click.product_id,
    )
