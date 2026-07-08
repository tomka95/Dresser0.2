"""Open-Meteo provider — the one place that talks to an external weather API.

Open-Meteo is free and needs NO API key (that's why it's the default). The base
URL is overridable via ``WEATHER_API_BASE_URL`` for self-hosting / tests; nothing
else here is configurable.

FAIL-SOFT CONTRACT: every path returns ``None`` on any trouble (network error,
non-200, malformed/partial JSON, missing temperature). Callers treat ``None`` as
"weather unavailable" and degrade gracefully — a weather outage never breaks a
chat turn, an outfit, or the Home tile. Response bodies are never logged (they're
low-sensitivity, but the codebase convention is status-only logging for outbound
calls).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.services.weather.models import (
    WeatherCurrent,
    WeatherToday,
    wmo_label,
)

logger = logging.getLogger(__name__)


@dataclass
class ProviderReading:
    """A validated reading normalized from the provider response. The service
    stamps provenance (provider/fetched/expires) + the warmth band around it."""

    current: WeatherCurrent
    today: WeatherToday
    timezone: str


def _num(value: Any) -> Optional[float]:
    """Coerce a JSON number defensively; None for anything non-numeric."""
    if isinstance(value, bool):  # bool is an int subclass — reject explicitly
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def fetch(lat: float, lon: float, timezone: Optional[str]) -> Optional[ProviderReading]:
    """Fetch current + today from Open-Meteo, or None on any failure.

    ``timezone`` is the caller's IANA zone (from onboarding); when absent we let
    Open-Meteo resolve it from the coordinates (``timezone=auto``) and record the
    zone it returns.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": timezone or "auto",
        "forecast_days": 1,
        "current": (
            "temperature_2m,apparent_temperature,precipitation,"
            "weather_code,is_day,wind_speed_10m"
        ),
        "daily": (
            "temperature_2m_max,temperature_2m_min,"
            "precipitation_probability_max,weather_code"
        ),
    }
    try:
        resp = httpx.get(
            settings.WEATHER_API_BASE_URL,
            params=params,
            timeout=settings.WEATHER_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("Open-Meteo returned HTTP %s", exc.response.status_code)
        return None
    except Exception as exc:  # noqa: BLE001 — network/timeout/JSON: all fail-soft
        logger.warning("Open-Meteo fetch failed: %s", type(exc).__name__)
        return None

    return _parse(data, timezone)


def _parse(data: dict, requested_tz: Optional[str]) -> Optional[ProviderReading]:
    """Validate the response shape. Temperature is REQUIRED (a reading without it
    is useless); everything else has a sane fallback."""
    if not isinstance(data, dict):
        return None
    current = data.get("current")
    daily = data.get("daily")
    if not isinstance(current, dict) or not isinstance(daily, dict):
        logger.warning("Open-Meteo response missing current/daily blocks")
        return None

    temp = _num(current.get("temperature_2m"))
    if temp is None:
        logger.warning("Open-Meteo response missing current temperature")
        return None
    feels = _num(current.get("apparent_temperature"))
    if feels is None:
        feels = temp  # apparent is optional; fall back to actual temp

    cur_code = current.get("weather_code")
    cur = WeatherCurrent(
        temp_c=temp,
        feels_like_c=feels,
        precip_mm=_num(current.get("precipitation")) or 0.0,
        condition=wmo_label(cur_code),
        code=int(cur_code) if isinstance(cur_code, (int, float)) else 0,
        is_day=bool(current.get("is_day", 1)),
        wind_kph=_num(current.get("wind_speed_10m")),
    )

    # Daily arrays are single-element (forecast_days=1). Guard index access.
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []
    codes = daily.get("weather_code") or []
    probs = daily.get("precipitation_probability_max") or []
    if not (isinstance(highs, list) and highs and isinstance(lows, list) and lows):
        logger.warning("Open-Meteo response missing daily high/low")
        return None

    day_code = codes[0] if isinstance(codes, list) and codes else None
    prob = probs[0] if isinstance(probs, list) and probs else None
    today = WeatherToday(
        high_c=_num(highs[0]) if _num(highs[0]) is not None else temp,
        low_c=_num(lows[0]) if _num(lows[0]) is not None else temp,
        precip_chance_pct=int(prob) if isinstance(prob, (int, float)) else None,
        condition=wmo_label(day_code),
        code=int(day_code) if isinstance(day_code, (int, float)) else 0,
    )

    # Open-Meteo echoes the resolved zone; prefer it so a "auto" request records a
    # concrete zone. Fall back to the requested zone, then UTC.
    resolved_tz = data.get("timezone")
    tz = resolved_tz if isinstance(resolved_tz, str) and resolved_tz else (requested_tz or "UTC")

    return ProviderReading(current=cur, today=today, timezone=tz)
