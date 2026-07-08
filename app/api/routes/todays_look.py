"""Today's Look — one auto-composed outfit for the day, on Home open.

    GET  /todays-look          -> the day's look (weather + calendar + profile)
    POST /todays-look/remix    -> an alternative look (excludes the shown items)
    POST /todays-look/wear     -> "Wear this": persist as a worn saved_outfit

DETERMINISTIC + PRIVATE:
  * Every DB read/write runs inside the RLS-scoped ``authenticated`` session
    (SET LOCAL role) so Postgres itself backstops the tenant filter; user_id is
    ALWAYS the JWT subject (get_current_user), never a request body.
  * Item ids in remix/wear pass the ownership choke point (get_owned_items) — a
    foreign or unknown id fails the whole call closed (422). Cross-user ids can
    never be composed or worn.
  * The composer derives an OCCASION + FORMALITY from the calendar; raw event
    titles are never read here and never persisted (assemble_calendar's contract).
  * Remix is rate-limited on the shared cross-worker limiter (chat_rate_windows).
  * Logs carry ids + counts only (no titles, no free text).
  * Fail-soft: GET never 500s Home — weather/calendar/collage errors degrade the
    look, and RLS-setup failure returns an empty-but-200 look rather than an error.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.dependencies import get_current_user
from app.models import SavedOutfit, User
from app.services.events_service import EventValidationError, log_event
from app.services.stylist import outfit_feedback as credit
from app.services.stylist.limits import RateLimited
from app.services.stylist.limits import check_rate_limit
from app.services.stylist.retrieval import get_owned_items
from app.services.stylist.rls import RlsSetupError, rls_scoped_session
from app.services.stylist.todays_look import TodaysLook, compose_todays_look

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/todays-look", tags=["todays-look"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class TodaysLookItem(BaseModel):
    id: str
    name: Optional[str] = None
    category: Optional[str] = None
    imageUrl: Optional[str] = None
    hasImage: bool = False


class TodaysLookResponse(BaseModel):
    model_config = ConfigDict(extra="allow")  # serialize_item carries extra attrs

    kind: str  # "look" | "starter"
    itemIds: List[str] = []
    items: List[Dict[str, Any]] = []
    collageUrl: Optional[str] = None
    title: str = ""
    caption: str = ""
    occasion: Optional[str] = None
    warmth: Optional[int] = None
    note: Optional[str] = None
    rationale: str = ""


class RemixIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # The currently-shown outfit's item ids — excluded so remix returns a variant.
    itemIds: List[str] = Field(default_factory=list, max_length=10)


class WearIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    itemIds: List[str] = Field(default_factory=list, max_length=10)
    title: Optional[str] = Field(None, max_length=120)
    rationale: Optional[str] = Field(None, max_length=600)
    occasion: Optional[str] = Field(None, max_length=60)


class WearAck(BaseModel):
    ok: bool
    outfitId: str
    itemCount: int
    idempotent: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _uuid(value: str, *, field: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail=f"{field} is not a valid id")


def _empty_look() -> Dict[str, Any]:
    """A 200 payload when the look genuinely can't be built (RLS down, etc.).
    Home renders its starter state rather than an error."""
    return TodaysLookResponse(
        kind="starter",
        note="Your look isn't available right now — pull to refresh.",
    ).model_dump()


def _log_shown(db: Session, user_id: UUID, look: TodaysLook, *, via: str) -> None:
    """Emit outfit_shown (ids + counts only). Best-effort; never breaks the response."""
    try:
        log_event(
            db,
            user_id=user_id,
            event_type="outfit_shown",
            entity_type="todays_look",
            source="system",
            properties={
                "item_count": len(look.item_ids),
                "kind": look.kind,
                "has_occasion": look.occasion is not None,
                "warmth": look.warmth,
                "via": via,
            },
        )
    except EventValidationError as exc:  # pragma: no cover - taxonomy is fixed
        logger.warning("todays_look outfit_shown rejected: %s", exc)


# ---------------------------------------------------------------------------
# GET /todays-look
# ---------------------------------------------------------------------------
@router.get("", response_model=TodaysLookResponse)
def todays_look(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    user_id = current_user.id
    try:
        with rls_scoped_session(user_id) as db:
            look = compose_todays_look(db, user_id)
            _log_shown(db, user_id, look, via="home")
            return look.to_payload()
    except RlsSetupError as exc:
        # Never 500 Home: degrade to an empty starter look.
        logger.error("todays_look RLS setup failed: %s", exc)
        return _empty_look()
    except Exception:  # noqa: BLE001 — Home must not 500 on this surface
        logger.exception("todays_look failed for user %s", user_id)
        return _empty_look()


# ---------------------------------------------------------------------------
# POST /todays-look/remix
# ---------------------------------------------------------------------------
@router.post("/remix", response_model=TodaysLookResponse)
def remix_todays_look(
    body: RemixIn,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    user_id = current_user.id

    # Shared cross-worker rate limit on its OWN owner session (the limiter
    # commits; doing that inside the RLS transaction would drop SET LOCAL).
    limiter_db = SessionLocal()
    try:
        check_rate_limit(limiter_db, user_id)
    except RateLimited as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after or 60)},
        )
    finally:
        limiter_db.close()

    exclude = [_uuid(i, field="itemIds[]") for i in body.itemIds]
    try:
        with rls_scoped_session(user_id) as db:
            look = compose_todays_look(db, user_id, exclude_item_ids=exclude)
            # The old outfit was waved off (reject) and a new one shown.
            if body.itemIds:
                try:
                    log_event(
                        db, user_id=user_id, event_type="outfit_reject",
                        entity_type="todays_look", source="system",
                        properties={"item_count": len(body.itemIds), "via": "remix"},
                    )
                except EventValidationError:  # pragma: no cover
                    pass
            _log_shown(db, user_id, look, via="remix")
            return look.to_payload()
    except RlsSetupError as exc:
        logger.error("todays_look remix RLS setup failed: %s", exc)
        raise HTTPException(status_code=503, detail="remix is unavailable right now")


# ---------------------------------------------------------------------------
# POST /todays-look/wear
# ---------------------------------------------------------------------------
@router.post("/wear", response_model=WearAck, status_code=201)
def wear_todays_look(
    body: WearIn,
    current_user: User = Depends(get_current_user),
) -> WearAck:
    user_id = current_user.id
    if not body.itemIds:
        raise HTTPException(status_code=422, detail="itemIds is required")
    item_ids = [_uuid(i, field="itemIds[]") for i in body.itemIds]

    try:
        with rls_scoped_session(user_id) as db:
            # Ownership choke point: fail CLOSED on any foreign/unknown id.
            owned = get_owned_items(db, user_id, item_ids)
            if len(owned) != len(set(item_ids)):
                raise HTTPException(
                    status_code=422,
                    detail="one or more item ids are not items in your closet",
                )

            # Idempotent per (user, item set, UTC day): a repeat "Wear this" for
            # the same look on the same day returns the existing row, no dup.
            id_set = {str(i.id) for i in owned}
            existing = _find_worn_today(db, user_id, id_set)
            if existing is not None:
                return WearAck(
                    ok=True, outfitId=str(existing.id),
                    itemCount=len(owned), idempotent=True,
                )

            now = datetime.utcnow()
            is_pg = db.bind is not None and db.bind.dialect.name == "postgresql"
            stored_ids = [i.id for i in owned] if is_pg else [str(i.id) for i in owned]
            saved = SavedOutfit(
                user_id=user_id,
                title=(body.title or None),
                item_ids=stored_ids,
                rationale=(body.rationale or None),
                occasion=(body.occasion or None),
                source="composer",
                status="worn",
                worn_at=now,
            )
            db.add(saved)
            db.flush()

            # Same learning loop as _tool_save_outfit + the worn feedback path:
            # an accept event, a worn event, and attribute-level reinforcement.
            event = log_event(
                db, user_id=user_id, event_type="outfit_accept",
                entity_type="saved_outfit", entity_id=str(saved.id),
                source="system",
                properties={"item_count": len(owned), "via": "todays_look"},
            )
            log_event(
                db, user_id=user_id, event_type="outfit_worn",
                entity_type="saved_outfit", entity_id=str(saved.id),
                source="system",
                properties={"item_count": len(owned), "via": "todays_look"},
            )
            db.flush()
            # Bump per-item wear telemetry (the composer rotates recently-worn
            # pieces down) + reinforce the combination into preference_signals.
            for it in owned:
                it.wear_count = int(it.wear_count or 0) + 1
                it.last_worn_at = now
            credit.apply_reinforce(db, user_id, owned, event_id=event.id)

            return WearAck(
                ok=True, outfitId=str(saved.id), itemCount=len(owned),
            )
    except HTTPException:
        raise
    except RlsSetupError as exc:
        logger.error("todays_look wear RLS setup failed: %s", exc)
        raise HTTPException(status_code=503, detail="saving is unavailable right now")
    except Exception:
        logger.exception("todays_look wear failed for user %s", user_id)
        raise HTTPException(status_code=500, detail="failed to save this look")


def _find_worn_today(
    db: Session, user_id: UUID, id_set: set[str]
) -> Optional[SavedOutfit]:
    """The user's composer look worn today with the exact same item set, if any.
    Item-set match is done in Python (uuid[] vs SQLite JSON array), scoped to the
    small set of today's composer-worn rows."""
    today = datetime.utcnow().date()
    rows = (
        db.query(SavedOutfit)
        .filter(
            SavedOutfit.user_id == user_id,
            SavedOutfit.source == "composer",
            SavedOutfit.status == "worn",
        )
        .order_by(SavedOutfit.worn_at.desc())
        .limit(50)
        .all()
    )
    for row in rows:
        if row.worn_at is None or row.worn_at.date() != today:
            continue
        if {str(x) for x in (row.item_ids or [])} == id_set:
            return row
    return None
