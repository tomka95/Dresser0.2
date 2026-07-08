"""Weather service — read-through cache over the Open-Meteo provider.

WHY ITS OWN SESSION (not the caller's RLS-scoped db): `weather_cache` has RLS
ENABLED WITH NO POLICIES (migration 0003) — it is deny-all for the
``authenticated`` role the stylist turn runs as. Weather is not per-user data; it
is location-keyed SHARED infrastructure (one row per ~1km cell serves everyone
there). So the service opens its OWN plain ``SessionLocal`` (the owner/service
role, which is not subject to RLS) for both the cache read and write, entirely
independent of any request's user-scoped session. Nothing user-scoped is read or
written here.

READ-THROUGH: on a hit within TTL we serve the cached payload; on a miss we call
the provider once, upsert the row (replacing any stale row for the same cell so
the table stays ~one-row-per-location), and return it. Every failure path returns
None — the caller degrades gracefully.

PRIVACY: latitude/longitude are rounded to 2 decimals (~1.1km) before they are
used as a cache key or sent to the provider. The client already coarsens on
capture; this is defense-in-depth so the service never persists or transmits a
finer location than intended.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from app.core.config import settings
from app.db import SessionLocal
from app.models import WeatherCache
from app.services.weather import open_meteo
from app.services.weather.models import WeatherForecast, warmth_band_from_temp

logger = logging.getLogger(__name__)

# ~1.1 km at the equator; matches the client-side coarsening on capture.
_COORD_PRECISION = 2


def _coarsen(value: float) -> float:
    return round(float(value), _COORD_PRECISION)


def extract_location(
    facts: Optional[Dict[str, Any]],
) -> Optional[Tuple[float, float, Optional[str]]]:
    """Pull (lat, lon, timezone?) from ``style_profiles.facts.location``.

    Onboarding screen 6 writes ``facts.location = {lat, lon, timezone?}`` (already
    coarsened client-side). Returns None when location is absent or malformed —
    the caller then reports 'no location' rather than guessing one.
    """
    loc = (facts or {}).get("location")
    if not isinstance(loc, dict):
        return None
    lat, lon = loc.get("lat"), loc.get("lon")
    if isinstance(lat, bool) or isinstance(lon, bool):
        return None
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    tz = loc.get("timezone")
    tz = tz if isinstance(tz, str) and tz.strip() else None
    return float(lat), float(lon), tz


def get_forecast(
    lat: float, lon: float, timezone_name: Optional[str] = None
) -> Optional[WeatherForecast]:
    """Read-through cache. Returns a fresh-or-cached forecast, or None if weather
    is disabled / the provider is unavailable."""
    if not settings.WEATHER_ENABLED:
        return None

    lat, lon = _coarsen(lat), _coarsen(lon)

    cached = _read_cache(lat, lon)
    if cached is not None:
        return cached

    reading = open_meteo.fetch(lat, lon, timezone_name)
    if reading is None:
        return None

    now = datetime.now(timezone.utc)
    forecast = WeatherForecast(
        provider=settings.WEATHER_PROVIDER,
        lat=lat,
        lon=lon,
        timezone=reading.timezone,
        fetched_at=now,
        expires_at=now + timedelta(seconds=settings.WEATHER_CACHE_TTL_SECONDS),
        current=reading.current,
        today=reading.today,
        warmth_band=warmth_band_from_temp(reading.current.feels_like_c),
    )
    _write_cache(forecast)
    return forecast


def forecast_for_facts(facts: Optional[Dict[str, Any]]) -> Optional[WeatherForecast]:
    """Convenience: extract the user's stored location and fetch its forecast.

    None when there is no usable location OR weather is unavailable — the caller
    distinguishes the two via :func:`extract_location` when it needs to."""
    loc = extract_location(facts)
    if loc is None:
        return None
    return get_forecast(*loc)


# --- Cache (own owner session; weather_cache is deny-all under RLS) -----------
def _read_cache(lat: float, lon: float) -> Optional[WeatherForecast]:
    """Freshest non-expired row for this cell, or None. Keyed on
    provider+lat+lon; timezone is derivable from the coordinates, so it is not
    part of the WHERE (avoids a 'auto' vs resolved-zone mismatch)."""
    now = datetime.now(timezone.utc)
    session = SessionLocal()
    try:
        row = (
            session.query(WeatherCache)
            .filter(
                WeatherCache.provider == settings.WEATHER_PROVIDER,
                WeatherCache.lat == lat,
                WeatherCache.lon == lon,
                WeatherCache.expires_at > now,
            )
            .order_by(WeatherCache.fetched_at.desc())
            .first()
        )
        if row is None:
            return None
        try:
            return WeatherForecast.model_validate(row.payload)
        except Exception as exc:  # noqa: BLE001 — a bad cached blob is a miss, not a crash
            logger.warning("Discarding unparseable weather_cache row: %s", type(exc).__name__)
            return None
    except Exception as exc:  # noqa: BLE001 — cache read must never break the caller
        logger.warning("weather_cache read failed: %s", type(exc).__name__)
        return None
    finally:
        session.close()


def _write_cache(forecast: WeatherForecast) -> None:
    """Replace any existing rows for this cell with the fresh forecast (keeps the
    table ~one-row-per-location). Best-effort: a write failure is logged and
    swallowed — the caller still got its live forecast."""
    session = SessionLocal()
    try:
        session.query(WeatherCache).filter(
            WeatherCache.provider == forecast.provider,
            WeatherCache.lat == forecast.lat,
            WeatherCache.lon == forecast.lon,
        ).delete(synchronize_session=False)
        session.add(
            WeatherCache(
                provider=forecast.provider,
                lat=forecast.lat,
                lon=forecast.lon,
                timezone=forecast.timezone,
                start_at=forecast.fetched_at,
                end_at=forecast.expires_at,
                payload=forecast.model_dump(mode="json"),
                fetched_at=forecast.fetched_at,
                expires_at=forecast.expires_at,
            )
        )
        session.commit()
    except Exception as exc:  # noqa: BLE001 — caching is best-effort
        session.rollback()
        logger.warning("weather_cache write failed: %s", type(exc).__name__)
    finally:
        session.close()
