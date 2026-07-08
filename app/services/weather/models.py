"""Typed weather payload — the `WeatherForecast` named (until now) only in the
`weather_cache.payload` column comment (app/models/ops.py:45).

This is the JSON shape stored in `weather_cache.payload` and returned by the
service. It is deliberately small and provider-neutral: an Open-Meteo reading is
normalized into these fields, so a future provider swap changes only the
provider module, never this model or its consumers.

Warmth band (1 hot .. 3 cold) is derived here from the feels-like temperature so
it matches the composer's existing `warmth_target` scale exactly (composer.py
`_warmth_ok`, 1 hot – 3 cold). The composer stays a PURE core — it never learns
where the band came from; the tool layer feeds this value into the existing
``warmth_target`` path.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

# Warmth-band thresholds (feels-like °C). These are DOMAIN logic, not deployment
# config, so they live here as constants rather than env vars: 1=hot (dress
# light, skip outerwear), 2=mild, 3=cold (layer up, outerwear slot fills). The
# bands line up with the composer's warmth 1..3 scale.
WARM_BAND_MIN_C = 22.0   # >= this feels hot -> band 1
COOL_BAND_MIN_C = 10.0   # [COOL, WARM) is mild -> band 2; below -> band 3 (cold)


def warmth_band_from_temp(feels_like_c: float) -> int:
    """Map a feels-like temperature to the composer's warmth band (1 hot..3 cold)."""
    if feels_like_c >= WARM_BAND_MIN_C:
        return 1
    if feels_like_c >= COOL_BAND_MIN_C:
        return 2
    return 3


# WMO weather-interpretation codes -> a short human label. Open-Meteo returns
# these integer codes for both current and daily conditions. Unknown codes fall
# back to a neutral label rather than raising (fail-soft everywhere).
WMO_LABELS = {
    0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Rain showers", 81: "Rain showers", 82: "Violent rain showers",
    85: "Snow showers", 86: "Snow showers",
    95: "Thunderstorm", 96: "Thunderstorm w/ hail", 99: "Thunderstorm w/ hail",
}


def wmo_label(code: Optional[int]) -> str:
    if code is None:
        return "Unknown"
    return WMO_LABELS.get(int(code), "Unsettled")


class WeatherCurrent(BaseModel):
    temp_c: float
    feels_like_c: float
    precip_mm: float = 0.0
    condition: str
    code: int
    is_day: bool = True
    wind_kph: Optional[float] = None


class WeatherToday(BaseModel):
    high_c: float
    low_c: float
    precip_chance_pct: Optional[int] = None
    condition: str
    code: int


class WeatherForecast(BaseModel):
    """Normalized forecast cached in `weather_cache.payload` and served to
    readers (the stylist `weather` tool, compose_outfit, GET /weather)."""

    provider: str
    lat: float
    lon: float
    timezone: str
    fetched_at: datetime
    expires_at: datetime
    current: WeatherCurrent
    today: WeatherToday
    # 1 hot .. 3 cold — matches the composer's warmth_target scale.
    warmth_band: int

    def to_public_dict(self) -> dict:
        """Compact, model-safe view shared by the `weather` tool result, the
        compose_outfit payload, and the GET /weather response. Raw temps /
        condition / precip are included so the LLM can mention them naturally."""
        return {
            "available": True,
            "current": {
                "temp_c": round(self.current.temp_c, 1),
                "feels_like_c": round(self.current.feels_like_c, 1),
                "condition": self.current.condition,
                "precip_mm": round(self.current.precip_mm, 2),
                "is_day": self.current.is_day,
            },
            "today": {
                "high_c": round(self.today.high_c, 1),
                "low_c": round(self.today.low_c, 1),
                "condition": self.today.condition,
                "precip_chance_pct": self.today.precip_chance_pct,
            },
            "warmth_band": self.warmth_band,
            "timezone": self.timezone,
            "as_of": self.fetched_at.isoformat(),
        }
