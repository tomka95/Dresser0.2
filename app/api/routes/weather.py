"""GET /weather — current + today's forecast for the authenticated user's
location, plus the derived warmth band (1 hot .. 3 cold).

Auth-guarded (Supabase access token). Location is read from the user's own
``style_profiles.facts.location`` (captured at onboarding, coarsened ~1km) — the
client never passes coordinates here, so a caller cannot probe arbitrary
locations through this endpoint.

Fail-soft: when the user hasn't shared a location, or the provider is
unavailable, the endpoint returns 200 with ``available: false`` and a reason,
never a 5xx — the Home tile just hides/greys rather than erroring.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models import StyleProfile, User
from app.services.weather import extract_location, get_forecast

router = APIRouter(tags=["weather"])


class WeatherResponse(BaseModel):
    available: bool
    reason: Optional[str] = None                # 'no_location' | 'unavailable'
    current: Optional[Dict[str, Any]] = None
    today: Optional[Dict[str, Any]] = None
    warmth_band: Optional[int] = None           # 1 hot .. 3 cold
    timezone: Optional[str] = None
    as_of: Optional[str] = None


@router.get("/weather", response_model=WeatherResponse)
def get_weather(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WeatherResponse:
    profile = (
        db.query(StyleProfile)
        .filter(StyleProfile.user_id == current_user.id)
        .one_or_none()
    )
    facts = (profile.facts or {}) if profile is not None else {}

    loc = extract_location(facts)
    if loc is None:
        return WeatherResponse(available=False, reason="no_location")

    forecast = get_forecast(*loc)
    if forecast is None:
        return WeatherResponse(available=False, reason="unavailable")

    return WeatherResponse(**forecast.to_public_dict())
