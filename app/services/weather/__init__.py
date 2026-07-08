"""Weather context source: Open-Meteo -> read-through weather_cache -> readers.

Public surface (import from here, not the submodules):
  * ``get_forecast(lat, lon, tz?)``   — read-through cached forecast, or None.
  * ``forecast_for_facts(facts)``     — same, keyed off style_profiles.facts.location.
  * ``extract_location(facts)``       — (lat, lon, tz?) or None.
  * ``WeatherForecast`` / ``warmth_band_from_temp`` — the payload model + warmth map.

Everything fails soft: a weather outage returns None and callers degrade.
"""
from app.services.weather.models import WeatherForecast, warmth_band_from_temp
from app.services.weather.service import (
    extract_location,
    forecast_for_facts,
    get_forecast,
)

__all__ = [
    "WeatherForecast",
    "warmth_band_from_temp",
    "extract_location",
    "forecast_for_facts",
    "get_forecast",
]
