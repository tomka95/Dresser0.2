"""Weather context source: provider parsing, warmth derivation, read-through
cache, the stylist `weather` tool, compose_outfit warmth wiring, GET /weather."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, engine
from app.models import StyleProfile, User, WeatherCache
from app.services.stylist.profile import ProfileBlock
from app.services.stylist.tools import ToolContext, dispatch_tool
from app.services.weather import extract_location, get_forecast, warmth_band_from_temp
from app.services.weather import open_meteo
from app.services.weather.models import WeatherForecast, wmo_label
from tests._authutil import mint_supabase_token
from main import app


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def user1(db: Session):
    u = User(email="wx1@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


# ---- sample provider payloads ----------------------------------------------
def _open_meteo_json(temp=8.0, feels=6.0, code=61, high=11.0, low=4.0, prob=80):
    return {
        "timezone": "America/New_York",
        "current": {
            "temperature_2m": temp,
            "apparent_temperature": feels,
            "precipitation": 0.3,
            "weather_code": code,
            "is_day": 1,
            "wind_speed_10m": 12.0,
        },
        "daily": {
            "temperature_2m_max": [high],
            "temperature_2m_min": [low],
            "precipitation_probability_max": [prob],
            "weather_code": [code],
        },
    }


# ---------------------------------------------------------------------------
# Warmth derivation (matches composer 1 hot .. 3 cold)
# ---------------------------------------------------------------------------
def test_warmth_band_thresholds():
    assert warmth_band_from_temp(30.0) == 1   # hot
    assert warmth_band_from_temp(22.0) == 1   # boundary -> hot
    assert warmth_band_from_temp(15.0) == 2   # mild
    assert warmth_band_from_temp(10.0) == 2   # boundary -> mild
    assert warmth_band_from_temp(3.0) == 3    # cold
    assert warmth_band_from_temp(-5.0) == 3


def test_wmo_label_known_and_unknown():
    assert wmo_label(0) == "Clear"
    assert wmo_label(61) == "Light rain"
    assert wmo_label(None) == "Unknown"
    assert wmo_label(1234) == "Unsettled"  # unknown code, no crash


# ---------------------------------------------------------------------------
# Provider parsing + fail-soft
# ---------------------------------------------------------------------------
def test_provider_parse_normalizes_reading():
    reading = open_meteo._parse(_open_meteo_json(), requested_tz=None)
    assert reading is not None
    assert reading.timezone == "America/New_York"
    assert reading.current.temp_c == 8.0
    assert reading.current.feels_like_c == 6.0
    assert reading.current.condition == "Light rain"
    assert reading.today.high_c == 11.0
    assert reading.today.precip_chance_pct == 80


def test_provider_parse_missing_temp_is_none():
    bad = _open_meteo_json()
    del bad["current"]["temperature_2m"]
    assert open_meteo._parse(bad, requested_tz=None) is None


def test_provider_parse_missing_daily_is_none():
    bad = _open_meteo_json()
    bad["daily"]["temperature_2m_max"] = []
    assert open_meteo._parse(bad, requested_tz=None) is None


def test_provider_apparent_falls_back_to_actual():
    j = _open_meteo_json(temp=12.0)
    del j["current"]["apparent_temperature"]
    reading = open_meteo._parse(j, requested_tz="Europe/Paris")
    assert reading.current.feels_like_c == 12.0


def test_provider_fetch_returns_none_on_http_error(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            import httpx
            raise httpx.HTTPStatusError("boom", request=None, response=_FakeResp(500))

    monkeypatch.setattr(open_meteo.httpx, "get", lambda *a, **k: _Resp())
    assert open_meteo.fetch(40.0, -74.0, "America/New_York") is None


class _FakeResp:
    def __init__(self, status):
        self.status_code = status


# ---------------------------------------------------------------------------
# extract_location
# ---------------------------------------------------------------------------
def test_extract_location_valid_and_invalid():
    assert extract_location({"location": {"lat": 40.7, "lon": -74.0, "timezone": "America/New_York"}}) == (
        40.7, -74.0, "America/New_York",
    )
    assert extract_location({"location": {"lat": 40.7, "lon": -74.0}}) == (40.7, -74.0, None)
    assert extract_location({}) is None
    assert extract_location({"location": "somewhere"}) is None
    assert extract_location({"location": {"lat": True, "lon": 1}}) is None  # bool rejected


# ---------------------------------------------------------------------------
# Read-through cache
# ---------------------------------------------------------------------------
def test_get_forecast_fetches_then_caches(db, monkeypatch):
    calls = {"n": 0}

    def fake_fetch(lat, lon, tz):
        calls["n"] += 1
        return open_meteo._parse(_open_meteo_json(), requested_tz=tz)

    monkeypatch.setattr(open_meteo, "fetch", fake_fetch)

    # Miss -> fetch + write.
    f1 = get_forecast(40.7128, -74.0060, "America/New_York")
    assert f1 is not None
    assert f1.warmth_band == 3            # feels 6°C -> cold
    assert calls["n"] == 1
    # coarsened to 2dp before caching
    assert f1.lat == 40.71 and f1.lon == -74.01
    assert db.query(WeatherCache).count() == 1

    # Hit -> served from cache, provider NOT called again.
    f2 = get_forecast(40.7128, -74.0060, "America/New_York")
    assert f2 is not None
    assert calls["n"] == 1
    assert db.query(WeatherCache).count() == 1  # replaced, not duplicated


def test_get_forecast_expired_row_refetches(db, monkeypatch):
    monkeypatch.setattr(
        open_meteo, "fetch",
        lambda lat, lon, tz: open_meteo._parse(_open_meteo_json(), requested_tz=tz),
    )
    # Seed an EXPIRED row for the cell.
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    db.add(WeatherCache(
        provider="open_meteo", lat=40.71, lon=-74.01, timezone="America/New_York",
        start_at=past, end_at=past, payload={"stale": True},
        fetched_at=past, expires_at=past,
    ))
    db.commit()

    f = get_forecast(40.7128, -74.0060, "America/New_York")
    assert f is not None and f.current.temp_c == 8.0   # fresh, not the stale blob


def test_get_forecast_disabled_returns_none(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "WEATHER_ENABLED", False)
    assert get_forecast(40.7, -74.0, "America/New_York") is None


def test_get_forecast_provider_unavailable_returns_none(db, monkeypatch):
    monkeypatch.setattr(open_meteo, "fetch", lambda *a, **k: None)
    assert get_forecast(40.7, -74.0, None) is None
    assert db.query(WeatherCache).count() == 0


# ---------------------------------------------------------------------------
# Stylist `weather` tool
# ---------------------------------------------------------------------------
def _ctx(db, user, facts=None):
    return ToolContext(db=db, user_id=user.id, profile=ProfileBlock(facts=facts or {}))


def test_weather_tool_no_location(db, user1):
    result = dispatch_tool(_ctx(db, user1, facts={}), "weather", {})
    assert result["available"] is False
    assert result["reason"] == "no_location"


def test_weather_tool_unavailable(db, user1, monkeypatch):
    monkeypatch.setattr(open_meteo, "fetch", lambda *a, **k: None)
    facts = {"location": {"lat": 40.7, "lon": -74.0, "timezone": "America/New_York"}}
    result = dispatch_tool(_ctx(db, user1, facts=facts), "weather", {})
    assert result["available"] is False
    assert result["reason"] == "unavailable"


def test_weather_tool_available(db, user1, monkeypatch):
    monkeypatch.setattr(
        open_meteo, "fetch",
        lambda lat, lon, tz: open_meteo._parse(_open_meteo_json(), requested_tz=tz),
    )
    facts = {"location": {"lat": 40.7, "lon": -74.0, "timezone": "America/New_York"}}
    result = dispatch_tool(_ctx(db, user1, facts=facts), "weather", {})
    assert result["available"] is True
    assert result["warmth_band"] == 3
    assert result["current"]["condition"] == "Light rain"
    assert "high_c" in result["today"]


def test_weather_tool_rejects_args(db, user1):
    # extra='forbid' — a stray arg fails closed, never executes.
    result = dispatch_tool(_ctx(db, user1), "weather", {"place": "Paris"})
    assert "error" in result


# ---------------------------------------------------------------------------
# compose_outfit warmth wiring (tool layer derives; composer stays pure)
# ---------------------------------------------------------------------------
def test_compose_outfit_derives_warmth_from_weather(db, user1, monkeypatch):
    import app.services.stylist.tools as tools_mod

    captured = {}

    def fake_compose(db_, uid, profile, **kw):
        captured.update(kw)
        from app.services.stylist.composer import ComposedOutfit
        return ComposedOutfit()

    monkeypatch.setattr(tools_mod, "compose_outfit", fake_compose)

    forecast = WeatherForecast(
        provider="open_meteo", lat=40.71, lon=-74.01, timezone="America/New_York",
        fetched_at=datetime.now(timezone.utc), expires_at=datetime.now(timezone.utc),
        current={"temp_c": 6, "feels_like_c": 5, "precip_mm": 0.3, "condition": "Light rain",
                 "code": 61, "is_day": True},
        today={"high_c": 9, "low_c": 3, "precip_chance_pct": 80, "condition": "Light rain", "code": 61},
        warmth_band=3,
    )
    monkeypatch.setattr(tools_mod, "forecast_for_facts", lambda facts: forecast)

    facts = {"location": {"lat": 40.7, "lon": -74.0, "timezone": "America/New_York"}}
    result = dispatch_tool(_ctx(db, user1, facts=facts), "compose_outfit", {"occasion": "walk"})
    # Derived band flowed into the composer's warmth_target path.
    assert captured["warmth_target"] == 3
    # Raw weather attached for the model to reference.
    assert result["weather"]["warmth_band"] == 3


def test_compose_outfit_explicit_warmth_overrides_weather(db, user1, monkeypatch):
    import app.services.stylist.tools as tools_mod

    captured = {}

    def fake_compose(db_, uid, profile, **kw):
        captured.update(kw)
        from app.services.stylist.composer import ComposedOutfit
        return ComposedOutfit()

    monkeypatch.setattr(tools_mod, "compose_outfit", fake_compose)

    def _boom(facts):
        raise AssertionError("weather must not be consulted when warmth is explicit")

    monkeypatch.setattr(tools_mod, "forecast_for_facts", _boom)

    result = dispatch_tool(_ctx(db, user1), "compose_outfit", {"warmth": 1})
    assert captured["warmth_target"] == 1
    assert "weather" not in result


# ---------------------------------------------------------------------------
# GET /weather endpoint
# ---------------------------------------------------------------------------
def test_weather_endpoint_no_location(db, user1, client, monkeypatch):
    db.add(StyleProfile(user_id=user1.id, facts={"sizes": {"top": "M"}}))
    db.commit()
    tok = mint_supabase_token(sub=str(user1.id))
    resp = client.get("/weather", headers={"Authorization": f"Bearer {tok}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["reason"] == "no_location"


def test_weather_endpoint_available(db, user1, client, monkeypatch):
    monkeypatch.setattr(
        open_meteo, "fetch",
        lambda lat, lon, tz: open_meteo._parse(_open_meteo_json(), requested_tz=tz),
    )
    db.add(StyleProfile(user_id=user1.id, facts={
        "location": {"lat": 40.7, "lon": -74.0, "timezone": "America/New_York"},
    }))
    db.commit()
    tok = mint_supabase_token(sub=str(user1.id))
    resp = client.get("/weather", headers={"Authorization": f"Bearer {tok}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["warmth_band"] == 3
    assert body["current"]["temp_c"] == 8.0


def test_weather_endpoint_requires_auth(client):
    assert client.get("/weather").status_code in (401, 403)
