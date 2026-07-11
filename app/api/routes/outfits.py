"""Lookbook backend — the real /outfits surface.

    GET    /outfits             -> the user's saved outfits (chat saves, worn
                                   Today's Looks, on-demand generates), newest first
    POST   /outfits/generate    -> compose ONE outfit on demand through the existing
                                   composer (weather + occasion + Style Profile) and,
                                   when it's a COMPLETE look, persist it as a
                                   saved_outfits row (source='composer')
    PUT    /outfits/{id}/like   -> like   (persisted: saved_outfits.is_liked)
    DELETE /outfits/{id}/like   -> unlike
    DELETE /outfits/{id}        -> unsave (delete the row)

REUSE, NOT REBUILD: composition is ``compose_lookbook_look`` — the exact Today's
Look pipeline (assemble_profile + derive_factors weather/calendar + the formality
step-down over the unchanged ``compose_outfit``) minus the collage. There is ONE
composer and ONE outfits table (saved_outfits, migration 0020) in this app.

HONESTY CONTRACT:
  * A generate that can't complete a look (closet gaps) returns 200 with
    ``sufficient=false`` + the composer's own ``gaps`` — nothing is persisted and
    nothing is force-filled. The client renders the honest empty state.
  * Every event this module emits carries a REAL saved_outfits id (the row is
    flushed before the event) or no entity id at all. No fabricated subjects.
  * item_ids in every returned outfit reference the caller's own clothing_items
    (they were validated at save time; RLS scopes every read).

SECURITY: user_id is ALWAYS the JWT subject (get_current_user), never a request
body. Every DB read/write runs inside the RLS-scoped ``authenticated`` session so
Postgres backstops the tenant filter. Foreign/unknown outfit ids 404 without
leaking existence. Generate shares the cross-worker rate limiter with remix.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.dependencies import get_current_user
from app.models import SavedOutfit, User
from app.services.events_service import EventValidationError, log_event
from app.services.stylist.limits import RateLimited, check_rate_limit
from app.services.stylist.rls import RlsSetupError, rls_scoped_session
from app.services.stylist.todays_look import compose_lookbook_look

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/outfits", tags=["outfits"])

# Statuses the Lookbook lists. 'rejected' and 'archived' are the user saying
# "not this one" — they stay out of the lookbook (but keep their learning rows).
_LISTED_STATUSES = ("active", "worn")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class OutfitOut(BaseModel):
    id: str
    userId: str
    name: Optional[str] = None
    items: List[str]
    occasion: Optional[str] = None
    rationale: Optional[str] = None
    source: str
    status: str
    isLiked: bool
    createdAt: str


class GenerateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    occasion: Optional[str] = Field(None, max_length=60)
    # Variety steering: the client passes item ids it's already showing so the
    # composer reaches for different pieces. Exclusion is harmless for foreign
    # ids (they were never in the pool), so no ownership check is needed here.
    excludeItemIds: List[str] = Field(default_factory=list, max_length=30)


class GenerateOut(BaseModel):
    model_config = ConfigDict(extra="allow")  # serialized items carry extra attrs
    saved: bool
    sufficient: bool
    gaps: List[str] = []
    note: Optional[str] = None
    outfit: Optional[OutfitOut] = None
    items: List[Dict[str, Any]] = []
    idempotent: bool = False


class LikeAck(BaseModel):
    ok: bool
    outfitId: str
    liked: bool


class UnsaveAck(BaseModel):
    ok: bool
    outfitId: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _uuid(value: str, *, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail=f"{field} is not a valid id")


def _serialize(row: SavedOutfit) -> OutfitOut:
    return OutfitOut(
        id=str(row.id),
        userId=str(row.user_id),
        name=row.title,
        items=[str(i) for i in (row.item_ids or [])],
        occasion=row.occasion,
        rationale=row.rationale,
        source=row.source,
        status=row.status,
        isLiked=bool(row.is_liked),
        createdAt=(row.created_at or datetime.utcnow()).isoformat(),
    )


def _own_outfit(db: Session, user_id: UUID, outfit_id: UUID) -> SavedOutfit:
    """The caller's outfit or 404. The user_id filter (with RLS behind it) means a
    foreign id is indistinguishable from a nonexistent one — no existence leak."""
    row = (
        db.query(SavedOutfit)
        .filter(SavedOutfit.user_id == user_id, SavedOutfit.id == outfit_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="outfit not found")
    return row


def _log_outfit_event(
    db: Session, user_id: UUID, event_type: str, outfit_id: Optional[UUID],
    properties: Dict[str, Any],
) -> None:
    """Emit one outfit event. entity_id is ALWAYS a real saved_outfits id (or
    absent) — this module never fabricates a subject. Best-effort."""
    try:
        log_event(
            db, user_id=user_id, event_type=event_type,
            entity_type="saved_outfit" if outfit_id is not None else None,
            entity_id=str(outfit_id) if outfit_id is not None else None,
            source="system", properties=properties,
        )
    except EventValidationError as exc:  # pragma: no cover - taxonomy is fixed
        logger.warning("outfits %s event rejected: %s", event_type, exc)


# ---------------------------------------------------------------------------
# GET /outfits
# ---------------------------------------------------------------------------
@router.get("", response_model=List[OutfitOut])
def list_outfits(
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
) -> List[OutfitOut]:
    user_id = current_user.id
    try:
        with rls_scoped_session(user_id) as db:
            rows = (
                db.query(SavedOutfit)
                .filter(
                    SavedOutfit.user_id == user_id,
                    SavedOutfit.status.in_(_LISTED_STATUSES),
                )
                .order_by(SavedOutfit.created_at.desc())
                .limit(limit)
                .all()
            )
            return [_serialize(r) for r in rows]
    except RlsSetupError as exc:
        logger.error("outfits list RLS setup failed: %s", exc)
        raise HTTPException(status_code=503, detail="outfits are unavailable right now")


# ---------------------------------------------------------------------------
# POST /outfits/generate
# ---------------------------------------------------------------------------
@router.post("/generate", response_model=GenerateOut)
def generate_outfit(
    body: GenerateIn,
    current_user: User = Depends(get_current_user),
) -> GenerateOut:
    user_id = current_user.id

    # Shared cross-worker rate limit on its OWN owner session (the limiter
    # commits; doing that inside the RLS transaction would drop SET LOCAL).
    limiter_db = SessionLocal()
    try:
        check_rate_limit(limiter_db, user_id)
    except RateLimited as exc:
        raise HTTPException(
            status_code=429, detail=str(exc),
            headers={"Retry-After": str(exc.retry_after or 60)},
        )
    finally:
        limiter_db.close()

    exclude_ids = [_uuid(i, field="excludeItemIds[]") for i in body.excludeItemIds]
    occasion = (body.occasion or "").strip() or None

    try:
        with rls_scoped_session(user_id) as db:
            look = compose_lookbook_look(
                db, user_id, occasion=occasion, exclude_item_ids=exclude_ids
            )
            outfit = look.outfit

            # HONEST GAP: no complete look — say so, persist nothing.
            if look.kind == "starter" or not outfit.slots:
                return GenerateOut(
                    saved=False,
                    sufficient=False,
                    gaps=list(outfit.gaps),
                    note=look.note or outfit.rationale or None,
                )

            # Complete look. Idempotency: the composer is deterministic, so the
            # same closet + factors reproduce the same item set — return the
            # existing row instead of stacking duplicates.
            item_id_set = {str(i) for i in look.item_ids}
            existing = _find_same_item_set(db, user_id, item_id_set)
            if existing is not None:
                return GenerateOut(
                    saved=True, sufficient=True,
                    outfit=_serialize(existing), items=list(look.items),
                    idempotent=True,
                )

            is_pg = db.bind is not None and db.bind.dialect.name == "postgresql"
            slot_items = list(outfit.slots.values())
            stored_ids = (
                [i.id for i in slot_items] if is_pg else [str(i.id) for i in slot_items]
            )
            saved = SavedOutfit(
                user_id=user_id,
                title=(look.title or None),
                item_ids=stored_ids,
                rationale=(outfit.rationale or None),
                occasion=(look.occasion or None),
                source="composer",
            )
            db.add(saved)
            db.flush()  # real id exists in the DB before any event references it

            _log_outfit_event(
                db, user_id, "outfit_shown", saved.id,
                {
                    "item_count": len(slot_items),
                    "has_occasion": look.occasion is not None,
                    "warmth": look.warmth,
                    "formality": look.formality,
                    "via": "lookbook_generate",
                },
            )
            return GenerateOut(
                saved=True, sufficient=True,
                outfit=_serialize(saved), items=list(look.items),
            )
    except HTTPException:
        raise
    except RlsSetupError as exc:
        logger.error("outfits generate RLS setup failed: %s", exc)
        raise HTTPException(status_code=503, detail="generate is unavailable right now")
    except Exception:
        logger.exception("outfits generate failed for user %s", user_id)
        raise HTTPException(status_code=500, detail="failed to generate an outfit")


def _find_same_item_set(
    db: Session, user_id: UUID, item_id_set: set[str]
) -> Optional[SavedOutfit]:
    """The user's newest listed composer outfit with the exact same item set."""
    rows = (
        db.query(SavedOutfit)
        .filter(
            SavedOutfit.user_id == user_id,
            SavedOutfit.source == "composer",
            SavedOutfit.status.in_(_LISTED_STATUSES),
        )
        .order_by(SavedOutfit.created_at.desc())
        .limit(50)
        .all()
    )
    for row in rows:
        if {str(x) for x in (row.item_ids or [])} == item_id_set:
            return row
    return None


# ---------------------------------------------------------------------------
# PUT/DELETE /outfits/{id}/like
# ---------------------------------------------------------------------------
def _set_liked(user_id: UUID, outfit_id_raw: str, liked: bool) -> LikeAck:
    outfit_id = _uuid(outfit_id_raw, field="outfit id")
    try:
        with rls_scoped_session(user_id) as db:
            row = _own_outfit(db, user_id, outfit_id)
            changed = bool(row.is_liked) != liked
            row.is_liked = liked
            row.liked_at = datetime.utcnow() if liked else None
            if changed:
                _log_outfit_event(
                    db, user_id, "outfit_rated", row.id,
                    {"liked": liked, "via": "lookbook"},
                )
            return LikeAck(ok=True, outfitId=str(row.id), liked=liked)
    except HTTPException:
        raise
    except RlsSetupError as exc:
        logger.error("outfits like RLS setup failed: %s", exc)
        raise HTTPException(status_code=503, detail="likes are unavailable right now")


@router.put("/{outfit_id}/like", response_model=LikeAck)
def like_outfit(
    outfit_id: str,
    current_user: User = Depends(get_current_user),
) -> LikeAck:
    return _set_liked(current_user.id, outfit_id, True)


@router.delete("/{outfit_id}/like", response_model=LikeAck)
def unlike_outfit(
    outfit_id: str,
    current_user: User = Depends(get_current_user),
) -> LikeAck:
    return _set_liked(current_user.id, outfit_id, False)


# ---------------------------------------------------------------------------
# DELETE /outfits/{id}  (unsave)
# ---------------------------------------------------------------------------
@router.delete("/{outfit_id}", response_model=UnsaveAck)
def unsave_outfit(
    outfit_id: str,
    current_user: User = Depends(get_current_user),
) -> UnsaveAck:
    user_id = current_user.id
    oid = _uuid(outfit_id, field="outfit id")
    try:
        with rls_scoped_session(user_id) as db:
            row = _own_outfit(db, user_id, oid)
            # Event first (entity_id references the still-real row; style_events
            # keeps ids as plain text, so the reference survives the delete).
            _log_outfit_event(
                db, user_id, "outfit_reject", row.id,
                {"via": "lookbook_unsave", "item_count": len(row.item_ids or [])},
            )
            db.delete(row)
            return UnsaveAck(ok=True, outfitId=str(oid))
    except HTTPException:
        raise
    except RlsSetupError as exc:
        logger.error("outfits unsave RLS setup failed: %s", exc)
        raise HTTPException(status_code=503, detail="unsave is unavailable right now")
