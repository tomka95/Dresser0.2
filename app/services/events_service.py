"""Interaction telemetry: the single write path into ``style_events``.

Wave S0 Branch C. Every meaningful user action becomes a ``StyleEvent`` row.
Two callers use this module:

  * server-derived events — ``log_event``/``log_events`` invoked *inside* existing
    handlers (gmail confirm, photo commit, PATCH edit/favorite). The handler already
    knows the authenticated ``user_id`` and the item ids, so nothing is trusted from
    the client here.
  * client-POSTed events — the ``POST /events`` route (see app/api/routes/events.py)
    validates an untrusted payload with :func:`normalize_client_event` and then calls
    :func:`log_events`.

SECURITY: ``user_id`` is ALWAYS supplied by the caller from the JWT subject, never
read from a request body. ``event_type`` is enum-validated (additive-only taxonomy).
``properties`` is size-capped and coerced to a flat JSON-safe dict — no PII beyond
item/entity references belongs there.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, Iterable, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import ClothingItem, StyleEvent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Taxonomy (ADDITIVE-ONLY). Never rename/remove a value — downstream analytics
# and the S1 distillation read historical rows by these exact strings. Add new
# event types to the end.
# ---------------------------------------------------------------------------
EVENT_TYPES: frozenset[str] = frozenset(
    {
        # Deck / feed impression + review
        "impression",        # a card was shown (properties: dwell_ms, feed_position)
        "expand",            # opened a detail view
        "save",              # accepted / kept into the closet
        "dismiss",           # rejected / swiped away
        "click_out",         # followed an outbound (retailer) link
        "wishlist_add",
        "purchase_confirmed",
        # Outfit lifecycle (S1 composer surfaces; reserved now)
        "outfit_shown",
        "outfit_accept",
        "outfit_reject",     # properties: reason_chips
        "outfit_modify",
        "outfit_worn",
        "outfit_rated",      # properties: rating
        # Closet surfaces
        "item_view",         # grid tile clicked / item surfaced
        "favorite",          # heart toggled (properties: value bool)
        "edit_field",        # a single field edited (properties: field)
        "archive",
        "donate",
        # Ingestion review
        "candidate_keep",    # detected garment committed for ingestion
        "candidate_discard",
        "region_select",     # region selector box toggled (properties: mode, index)
        # Session bookends
        "session_start",
        "session_end",
        # Shopping feed (Wave F2). impression/expand/save/dismiss/click_out/wishlist_add
        # above are reused by the feed (card_type/feed_position/exploration/session_id ride
        # in `properties`). rate_swipe is the feed's like/dislike swipe on a card — a
        # behavioural taste signal the F3 learning loop reads.
        "rate_swipe",
    }
)

# Sources are a soft, free-text taxonomy (the DB column is TEXT). Documented here so
# emitters stay consistent; not enforced, so new surfaces can appear without a change.
KNOWN_SOURCES = frozenset(
    {
        "closet_grid",
        "closet_detail",
        "review_deck",
        "photo_detect",
        "gmail",
        "photo",
        "system",
    }
)

# Keep `properties` shallow and small. Values must be JSON primitives (or short
# lists of them); nested objects/arrays-of-objects are rejected. This is both a
# size guard and a PII guard — free-form nested blobs are where email bodies,
# addresses, etc. would leak in.
_ALLOWED_PROP_SCALARS = (str, int, float, bool, type(None))
_MAX_PROP_KEYS = 32
_MAX_STR_LEN = 512


class EventValidationError(ValueError):
    """Raised when an untrusted client event fails validation. The message names
    only field/enum problems — never echoes payload content — so it is safe to
    surface to the caller as an HTTP 422 detail."""


# ---------------------------------------------------------------------------
# Property sanitation
# ---------------------------------------------------------------------------
def _sanitize_properties(properties: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Coerce an arbitrary dict into a flat, small, JSON-safe properties blob.

    Rules: dict only; <= _MAX_PROP_KEYS keys; string keys; values are scalars or
    short lists of scalars; strings truncated to _MAX_STR_LEN; serialized size
    capped at settings.EVENTS_MAX_PROPERTIES_BYTES. Raises EventValidationError.
    """
    if properties is None:
        return {}
    if not isinstance(properties, dict):
        raise EventValidationError("properties must be an object")
    if len(properties) > _MAX_PROP_KEYS:
        raise EventValidationError(f"properties has too many keys (max {_MAX_PROP_KEYS})")

    clean: Dict[str, Any] = {}
    for key, value in properties.items():
        if not isinstance(key, str):
            raise EventValidationError("properties keys must be strings")
        if isinstance(value, list):
            if len(value) > _MAX_PROP_KEYS or not all(
                isinstance(v, _ALLOWED_PROP_SCALARS) for v in value
            ):
                raise EventValidationError(
                    f"properties[{key!r}] must be a short list of scalars"
                )
            clean[key] = [
                v[:_MAX_STR_LEN] if isinstance(v, str) else v for v in value
            ]
        elif isinstance(value, _ALLOWED_PROP_SCALARS):
            clean[key] = value[:_MAX_STR_LEN] if isinstance(value, str) else value
        else:
            raise EventValidationError(
                f"properties[{key!r}] must be a scalar or list of scalars"
            )

    encoded = json.dumps(clean, separators=(",", ":"), default=str)
    if len(encoded.encode("utf-8")) > settings.EVENTS_MAX_PROPERTIES_BYTES:
        raise EventValidationError(
            f"properties exceeds {settings.EVENTS_MAX_PROPERTIES_BYTES} bytes"
        )
    return clean


def _coerce_uuid(value: Any, field: str) -> Optional[UUID]:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        raise EventValidationError(f"{field} is not a valid UUID")


# ---------------------------------------------------------------------------
# Write path
# ---------------------------------------------------------------------------
def log_event(
    db: Session,
    *,
    user_id: UUID,
    event_type: str,
    item_id: Optional[UUID] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    source: Optional[str] = None,
    properties: Optional[Dict[str, Any]] = None,
    session_id: Optional[UUID] = None,
    commit: bool = False,
) -> StyleEvent:
    """Append one style_events row. Adds to the session; caller controls the txn.

    ``event_type`` is enum-validated; ``properties`` is sanitized. ``user_id`` is
    the caller's responsibility (always a JWT subject). ``item_id`` is NOT verified
    for ownership here — server-derived callers pass ids they already own; the
    client route pre-validates ownership before calling.

    Raises EventValidationError on a bad event_type / properties.
    """
    if event_type not in EVENT_TYPES:
        raise EventValidationError(f"unknown event_type: {event_type!r}")

    event = StyleEvent(
        user_id=user_id,
        event_type=event_type,
        item_id=item_id,
        entity_type=entity_type,
        entity_id=(str(entity_id)[:_MAX_STR_LEN] if entity_id is not None else None),
        source=(str(source)[:_MAX_STR_LEN] if source is not None else None),
        properties=_sanitize_properties(properties),
        session_id=session_id,
    )
    db.add(event)
    if commit:
        db.commit()
    return event


def log_events(db: Session, user_id: UUID, events: Iterable[Dict[str, Any]]) -> int:
    """Append many pre-normalized events in the caller's transaction.

    Each dict is passed as kwargs to :func:`log_event`. Returns the count added.
    Does NOT commit — the caller decides when to flush.
    """
    count = 0
    for ev in events:
        log_event(db, user_id=user_id, **ev)
        count += 1
    return count


# Client-POSTed entity types whose entity_id MUST reference one of the caller's
# own saved_outfits rows. This closes the fabricated-outfit-id door: in the mock
# era the web client attached likes to outfit UUIDs that existed nowhere, and
# nothing rejected them. Server-derived emitters are unaffected (they only ever
# pass freshly-flushed row ids).
_OUTFIT_ENTITY_TYPES = frozenset({"saved_outfit", "outfit"})


def normalize_client_event(
    raw: Dict[str, Any],
    *,
    db: Session,
    user_id: UUID,
    owned_item_ids: set[UUID],
    owned_outfit_ids: Optional[set[UUID]] = None,
) -> Dict[str, Any]:
    """Validate one UNTRUSTED client event into log_event kwargs.

    Enforces every client-facing rule:
      * event_type must be in the taxonomy,
      * item_id (if given) must belong to ``user_id`` — a client cannot attach an
        event to another user's item,
      * an outfit entityId (entityType in _OUTFIT_ENTITY_TYPES) must reference one
        of the caller's saved_outfits rows — fabricated outfit subjects are
        rejected, never stored,
      * properties are sanitized/size-capped,
      * user_id can NEVER come from the payload (ignored if present).

    ``owned_item_ids`` / ``owned_outfit_ids`` are the pre-fetched sets of the
    caller's ids referenced across the batch, so ownership is checked with one
    query each, not one-per-event. Raises EventValidationError.
    """
    event_type = raw.get("eventType") or raw.get("event_type")
    if not isinstance(event_type, str) or event_type not in EVENT_TYPES:
        raise EventValidationError(f"unknown or missing event_type: {event_type!r}")

    item_id = _coerce_uuid(raw.get("itemId") or raw.get("item_id"), "itemId")
    if item_id is not None and item_id not in owned_item_ids:
        # Do not leak whether the id exists for another user — treat as invalid.
        raise EventValidationError("itemId does not reference one of your items")

    session_id = _coerce_uuid(raw.get("sessionId") or raw.get("session_id"), "sessionId")

    entity_type = raw.get("entityType") or raw.get("entity_type")
    entity_id = raw.get("entityId") or raw.get("entity_id")
    source = raw.get("source")
    for name, val in (("entityType", entity_type), ("source", source)):
        if val is not None and not isinstance(val, str):
            raise EventValidationError(f"{name} must be a string")

    # Outfit subjects must be REAL: an outfit-typed entity_id has to reference one
    # of the caller's own saved_outfits rows (same non-leaking posture as itemId).
    if entity_type in _OUTFIT_ENTITY_TYPES and entity_id is not None:
        outfit_id = _coerce_uuid(entity_id, "entityId")
        if outfit_id not in (owned_outfit_ids or set()):
            raise EventValidationError(
                "entityId does not reference one of your saved outfits"
            )

    return {
        "event_type": event_type,
        "item_id": item_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "source": source,
        "properties": _sanitize_properties(raw.get("properties")),
        "session_id": session_id,
    }


def owned_item_ids_in(db: Session, user_id: UUID, item_ids: Iterable[UUID]) -> set[UUID]:
    """Return the subset of ``item_ids`` that belong to ``user_id`` (one query)."""
    ids = {i for i in item_ids if i is not None}
    if not ids:
        return set()
    rows = (
        db.query(ClothingItem.id)
        .filter(ClothingItem.user_id == user_id, ClothingItem.id.in_(ids))
        .all()
    )
    return {r[0] for r in rows}


def owned_outfit_ids_in(
    db: Session, user_id: UUID, outfit_ids: Iterable[UUID]
) -> set[UUID]:
    """Return the subset of ``outfit_ids`` that are ``user_id``'s saved_outfits
    rows (one query) — the ownership prefetch for outfit-typed entity ids."""
    from app.models import SavedOutfit

    ids = {i for i in outfit_ids if i is not None}
    if not ids:
        return set()
    rows = (
        db.query(SavedOutfit.id)
        .filter(SavedOutfit.user_id == user_id, SavedOutfit.id.in_(ids))
        .all()
    )
    return {r[0] for r in rows}
