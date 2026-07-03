"""Onboarding seed + status — the S1 tap-only onboarding's server round-trip.

Wave S1. The 6-screen onboarding (departments, sizes, fit sliders, taste deck,
occasions, weather/closet) stages every answer client-side and commits ONCE here:

  * POST /onboarding/seed   — write facts + preferences + signals, stamp completion.
  * GET  /onboarding/status — cheap {completed} read for the frontend gate.

SECURITY / ABUSE GUARDS (see app/services/onboarding_service.py for the rest):
  * user_id is the JWT subject (get_current_user), NEVER the request body.
  * source is forced to 'onboarding'; confidence clamped to the onboarding band.
  * facts/value blobs are depth+size capped; typed columns never take raw blobs.
  * batch sizes capped at settings.ONBOARDING_MAX_* -> 422 over-limit.
  * idempotent: profile upserts on user_id, preferences on (user_id, dimension) —
    re-running onboarding never 409s.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dependencies import get_current_user, get_db
from app.models import User
from app.services.onboarding_service import (
    OnboardingValidationError,
    onboarding_completed,
    sanitize_facts,
    seed_preference_signals,
    seed_style_preferences,
    seed_style_profile,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class PreferenceIn(BaseModel):
    """One structured preference (e.g. an occasion or color axis). source and
    confidence are server-owned; a client-sent source is ignored."""

    dimension: str = Field(..., description="Preference axis, e.g. 'occasion' or 'color'")
    value: Optional[Dict[str, Any]] = Field(None, description="Structured value payload")
    polarity: Optional[str] = Field(None, description="like | dislike | neutral")
    confidence: Optional[float] = Field(None, description="Clamped to the onboarding band")

    class Config:
        extra = "ignore"


class SignalIn(BaseModel):
    """One raw preference signal (e.g. a taste-deck swipe). item_id/event_id are
    never accepted from the client."""

    signalType: str = Field(..., description="Signal kind, e.g. 'taste_swipe'")
    key: Optional[str] = Field(None, description="Signal key, e.g. an archetype name")
    value: Optional[Dict[str, Any]] = None
    polarity: Optional[str] = Field(None, description="like | dislike | neutral")
    weight: Optional[float] = Field(None, description="Signal strength, clamped to [0,1]")

    class Config:
        extra = "ignore"


class OnboardingSeedIn(BaseModel):
    """The full onboarding result. Every part optional — screens are skippable."""

    facts: Optional[Dict[str, Any]] = Field(
        None, description="Sizes/departments/fits/location/occasions -> style_profiles.facts"
    )
    preferences: Optional[List[PreferenceIn]] = None
    signals: Optional[List[SignalIn]] = None

    class Config:
        extra = "ignore"


class OnboardingSeedAck(BaseModel):
    profileId: str
    preferencesUpserted: int
    signalsInserted: int


class OnboardingStatus(BaseModel):
    completed: bool


@router.post("/seed", response_model=OnboardingSeedAck, status_code=201)
def seed_onboarding(
    body: OnboardingSeedIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OnboardingSeedAck:
    """Persist the authenticated user's onboarding answers in one transaction."""
    preferences = body.preferences or []
    signals = body.signals or []

    if len(preferences) > settings.ONBOARDING_MAX_PREFERENCES:
        raise HTTPException(
            status_code=422,
            detail=f"too many preferences (max {settings.ONBOARDING_MAX_PREFERENCES})",
        )
    if len(signals) > settings.ONBOARDING_MAX_SIGNALS:
        raise HTTPException(
            status_code=422,
            detail=f"too many signals (max {settings.ONBOARDING_MAX_SIGNALS})",
        )

    try:
        facts = sanitize_facts(body.facts)
        pref_dicts = [p.model_dump() for p in preferences]
        signal_dicts = [s.model_dump() for s in signals]
    except OnboardingValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        profile = seed_style_profile(db, current_user.id, facts)
        pref_count = seed_style_preferences(db, current_user.id, pref_dicts)
        signal_count = seed_preference_signals(db, current_user.id, signal_dicts)
        db.flush()
        profile_id = str(profile.id)
        db.commit()
    except OnboardingValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        db.rollback()
        logger.exception("Failed to seed onboarding for user %s", current_user.id)
        raise HTTPException(status_code=500, detail="failed to seed onboarding")

    return OnboardingSeedAck(
        profileId=profile_id,
        preferencesUpserted=pref_count,
        signalsInserted=signal_count,
    )


@router.get("/status", response_model=OnboardingStatus)
def get_onboarding_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OnboardingStatus:
    """Cheap completion check for the client-side onboarding gate."""
    return OnboardingStatus(completed=onboarding_completed(db, current_user.id))
