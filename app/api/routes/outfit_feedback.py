"""POST /outfits/feedback — outfit reject / modify / worn -> learning (Wave S3).

Closes the outfit learning loop. Until now only ``outfit_accept`` fired (save_outfit
-> a saved_outfits row). This route wires the three reserved reactions the chat
composer now offers on a composed outfit:

  * reject  — the user waved an outfit off, optionally with reason chips
              (color / formality / weather / not-my-style / fit / item-specific).
  * modify  — the user swapped one slot's item for another (removed + replacement).
  * worn    — the next-day one-tap "I actually wore this".

Each reaction becomes BOTH a ``style_events`` telemetry row (the existing taxonomy:
outfit_reject / outfit_modify / outfit_worn) AND per-item, per-attribute
``preference_signals`` (source='outfit_feedback') via the credit-assignment module,
which the s3a distill/redistill pipeline folds into typed style_preferences —
outranking inferred signals, ranking below user-stated ones.

SECURITY / ABUSE GUARDS (mirrors POST /events):
  * user_id is the JWT subject (get_current_user), NEVER the request body.
  * every referenced item id must belong to the caller — resolved through the
    retrieval ownership choke point; any foreign/unknown id fails the whole call
    closed (422), so a coerced id can never attach feedback to another user's item.
  * all DB work runs inside the RLS-scoped agent session (SET LOCAL role
    authenticated), so Postgres itself backstops the tenant filter.
  * reason chips are enum-validated; event ``properties`` carry only chips / counts /
    a slot name — never free text or message content (no PII in logs).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.dependencies import get_current_user
from app.models import ClothingItem, SavedOutfit, User
from app.services.events_service import EventValidationError, log_event
from app.services.stylist import outfit_feedback as credit
from app.services.stylist.retrieval import get_owned_items
from app.services.stylist.rls import RlsSetupError, rls_scoped_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/outfits", tags=["outfits"])

_FEEDBACK_EVENT = {
    "reject": "outfit_reject",
    "modify": "outfit_modify",
    "worn": "outfit_worn",
}


# ---------------------------------------------------------------------------
# Request schema (extra='forbid'; sizes bounded by pydantic)
# ---------------------------------------------------------------------------
class OutfitFeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback: Literal["reject", "modify", "worn"]
    # The composed outfit's item ids (as rendered in chat). Required for reject/worn
    # unless a savedOutfitId is given; the modify path uses removed/replacement.
    itemIds: List[str] = Field(default_factory=list, max_length=8)
    # If the reaction is to a SAVED outfit, its id — we flip its status/worn_at.
    savedOutfitId: Optional[str] = Field(None, max_length=40)
    conversationId: Optional[str] = Field(None, max_length=40)

    # reject
    reasonChips: List[str] = Field(default_factory=list, max_length=6)
    directions: Dict[str, str] = Field(default_factory=dict)
    itemId: Optional[str] = Field(None, max_length=40)  # item-specific reject target

    # modify (swap)
    removedItemId: Optional[str] = Field(None, max_length=40)
    replacementItemId: Optional[str] = Field(None, max_length=40)
    slot: Optional[str] = Field(None, max_length=20)


class OutfitFeedbackAck(BaseModel):
    ok: bool
    eventType: str
    signals: int
    status: Optional[str] = None


def _uuid(value: Optional[str], *, field: str) -> Optional[UUID]:
    if value is None:
        return None
    try:
        return UUID(value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail=f"{field} is not a valid id")


@router.post("/feedback", response_model=OutfitFeedbackAck, status_code=202)
def outfit_feedback_route(
    body: OutfitFeedbackIn,
    current_user: User = Depends(get_current_user),
) -> OutfitFeedbackAck:
    user_id = current_user.id
    event_type = _FEEDBACK_EVENT[body.feedback]

    # Validate reason chips up front (before any DB work) — unknown chip -> 422.
    bad = [c for c in body.reasonChips if c not in credit.REASON_CHIPS]
    if bad:
        raise HTTPException(status_code=422, detail=f"unknown reason chip(s): {sorted(set(bad))}")
    directions = {
        k: v for k, v in body.directions.items()
        if isinstance(v, str) and v in credit.REASON_DIRECTIONS
    }

    saved_id = _uuid(body.savedOutfitId, field="savedOutfitId")
    outfit_ids = [_uuid(i, field="itemIds[]") for i in body.itemIds]
    item_specific_id = _uuid(body.itemId, field="itemId")
    removed_id = _uuid(body.removedItemId, field="removedItemId")
    replacement_id = _uuid(body.replacementItemId, field="replacementItemId")

    if body.feedback == "modify" and (removed_id is None or replacement_id is None):
        raise HTTPException(
            status_code=422,
            detail="modify requires removedItemId and replacementItemId",
        )

    try:
        with rls_scoped_session(user_id) as db:
            saved = _resolve_saved(db, user_id, saved_id)

            # For a worn/reject against a saved outfit with no explicit item list,
            # fall back to the saved outfit's own items.
            if not outfit_ids and saved is not None and saved.item_ids:
                outfit_ids = [_coerce(i) for i in saved.item_ids]
                outfit_ids = [i for i in outfit_ids if i is not None]

            # Resolve + ownership-check EVERY referenced id in one query (choke point).
            referenced = {
                i for i in (
                    *outfit_ids, item_specific_id, removed_id, replacement_id
                ) if i is not None
            }
            owned = {i.id: i for i in get_owned_items(db, user_id, referenced)}
            missing = referenced - set(owned)
            if missing:
                # Do not leak whether the id exists for another user — invalid, full stop.
                raise HTTPException(
                    status_code=422,
                    detail="one or more item ids are not items in your closet",
                )

            outfit_items = [owned[i] for i in outfit_ids if i in owned]
            props = _event_props(body, outfit_items, directions, saved)

            try:
                event = log_event(
                    db, user_id=user_id, event_type=event_type,
                    entity_type="outfit",
                    entity_id=str(saved.id) if saved is not None else None,
                    source="system", properties=props,
                )
            except EventValidationError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            db.flush()
            event_id = event.id

            signals = _dispatch(
                db, user_id, body, outfit_items, owned,
                item_specific_id, removed_id, replacement_id, directions, event_id,
            )
            _update_saved(saved, body.feedback, body.reasonChips, body.slot,
                          directions, len(signals))

            return OutfitFeedbackAck(
                ok=True, eventType=event_type, signals=len(signals),
                status=(saved.status if saved is not None else None),
            )
    except HTTPException:
        raise
    except RlsSetupError as exc:
        logger.error("outfit feedback RLS setup failed: %s", exc)
        raise HTTPException(status_code=503, detail="feedback is unavailable right now")
    except Exception:
        logger.exception("outfit feedback failed for user %s", user_id)
        raise HTTPException(status_code=500, detail="failed to record outfit feedback")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _coerce(value: Any) -> Optional[UUID]:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None


def _resolve_saved(
    db: Session, user_id: UUID, saved_id: Optional[UUID]
) -> Optional[SavedOutfit]:
    """The caller's saved outfit, or None (foreign/unknown ids fail closed to None —
    no 404 that would leak whether the id exists for another user)."""
    if saved_id is None:
        return None
    return (
        db.query(SavedOutfit)
        .filter(SavedOutfit.id == saved_id, SavedOutfit.user_id == user_id)
        .one_or_none()
    )


def _event_props(
    body: OutfitFeedbackIn,
    outfit_items: List[ClothingItem],
    directions: Dict[str, str],
    saved: Optional[SavedOutfit],
) -> Dict[str, Any]:
    """FLAT, PII-free event properties (the sanitizer rejects nested objects)."""
    props: Dict[str, Any] = {"item_count": len(outfit_items), "via": "chat",
                             "saved": saved is not None}
    if body.feedback == "reject":
        props["reason_chips"] = list(body.reasonChips)
        props["item_specific"] = body.itemId is not None
        if directions.get("formality"):
            props["formality_direction"] = directions["formality"]
    elif body.feedback == "modify" and body.slot:
        props["slot"] = body.slot
    return props


def _dispatch(
    db: Session,
    user_id: UUID,
    body: OutfitFeedbackIn,
    outfit_items: List[ClothingItem],
    owned: Dict[UUID, ClothingItem],
    item_specific_id: Optional[UUID],
    removed_id: Optional[UUID],
    replacement_id: Optional[UUID],
    directions: Dict[str, str],
    event_id: UUID,
) -> List[Any]:
    """Route the reaction to the credit-assignment module."""
    if body.feedback == "reject":
        return credit.apply_reject(
            db, user_id, outfit_items,
            reason_chips=body.reasonChips, directions=directions,
            item_specific=owned.get(item_specific_id) if item_specific_id else None,
            event_id=event_id,
        )
    if body.feedback == "modify":
        removed = owned[removed_id]        # presence guaranteed by the ownership gate
        replacement = owned[replacement_id]
        kept = [i for i in outfit_items if i.id not in (removed_id, replacement_id)]
        return credit.apply_modify(
            db, user_id, removed, replacement, kept=kept, event_id=event_id)
    # worn: reinforce the combination AND bump each item's wear telemetry — the
    # composer reads wear_count / last_worn_at to rotate recently-worn pieces down.
    now = datetime.utcnow()
    for it in outfit_items:
        it.wear_count = int(it.wear_count or 0) + 1
        it.last_worn_at = now
    return credit.apply_reinforce(db, user_id, outfit_items, event_id=event_id)


def _update_saved(
    saved: Optional[SavedOutfit],
    feedback: str,
    reason_chips: List[str],
    slot: Optional[str],
    directions: Dict[str, str],
    signal_count: int,
) -> None:
    """Reflect the feedback onto the saved_outfits row (if the reaction targeted one).
    Sets the outfit-level lifecycle; per-item wear_count is bumped in _dispatch."""
    if saved is None:
        return
    now = datetime.utcnow()
    if feedback == "worn":
        saved.status = "worn"
        saved.worn_at = now
    elif feedback == "reject":
        saved.status = "rejected"
    saved.feedback = {
        "feedback": feedback,
        "reason_chips": list(reason_chips),
        "slot": slot,
        "direction": directions.get("formality"),
        "signals": signal_count,
    }
