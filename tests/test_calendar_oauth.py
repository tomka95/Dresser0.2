"""Calendar-connect OAuth + live calendar context.

Security focus: cross-flow state-replay rejection (a Gmail state cannot attach a
calendar grant), forged/expired state, per-user scoping of calendar_accounts, and
the RLS-scoped read path the 0027 GRANT enables. Plus exchange/disconnect and the
assemble_calendar → compose_outfit dress-context wiring.
"""

import base64
import os
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.core.calendar_oauth_state as cal_state
import app.core.gmail_oauth_state as gmail_state
from app.core import token_crypto
from app.core.calendar_oauth_state import OAuthStateError, issue_state, verify_state
from app.db import Base, SessionLocal, engine
from app.models import CalendarAccount, User
from app.services.stylist.calendar import (
    CalendarBlock,
    assemble_calendar,
    derive_dress_context,
    resolve_target_date,
)
import app.services.stylist.calendar as stylist_cal
from app.calendar_context import CalendarEvent
from app.services.stylist.profile import ProfileBlock
from app.services.stylist.tools import ToolContext, dispatch_tool
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
    u = User(email="cal1@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture
def user2(db: Session):
    u = User(email="cal2@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture(autouse=True)
def _clear_calendar_caches():
    """Isolate the per-(user, window) live-fetch cache between tests."""
    stylist_cal._events_cache.clear()
    yield
    stylist_cal._events_cache.clear()


@pytest.fixture(autouse=True)
def _crypto_and_secrets(monkeypatch):
    """Configure token encryption + OAuth client/state so the flow is exercisable."""
    from app.core.config import settings
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "GMAIL_TOKEN_ENC_KEY", key)
    token_crypto._key.cache_clear()
    monkeypatch.setattr(settings, "CALENDAR_OAUTH_CLIENT_ID", "cal-client")
    monkeypatch.setattr(settings, "CALENDAR_OAUTH_CLIENT_SECRET", "cal-secret")
    monkeypatch.setattr(settings, "CALENDAR_OAUTH_STATE_SECRET", "unit-test-secret")
    yield
    token_crypto._key.cache_clear()


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def _seed_connected(db, user):
    """A connected calendar account with encrypted tokens."""
    from app.core.token_crypto import encrypt_token
    acct = CalendarAccount(
        user_id=user.id,
        access_token=encrypt_token("access-plain", field="access_token"),
        refresh_token=encrypt_token("refresh-plain", field="refresh_token"),
        scope="https://www.googleapis.com/auth/calendar.events.readonly",
        token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(acct); db.commit(); db.refresh(acct)
    return acct


# ---------------------------------------------------------------------------
# State: cross-flow replay, forgery, expiry, user-binding
# ---------------------------------------------------------------------------
def test_gmail_state_rejected_at_calendar_callback(monkeypatch):
    """A Gmail-issued state must NOT verify for the calendar flow. Share the
    secret so the SIGNATURE validates — proving the PURPOSE binding is the gate."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "GMAIL_OAUTH_STATE_SECRET", "unit-test-secret")
    uid = str(uuid.uuid4())
    gmail_token = gmail_state.issue_state(uid)  # purpose=gmail_oauth_connect
    with pytest.raises(OAuthStateError, match="wrong purpose"):
        verify_state(gmail_token, expected_user_id=uid)


def test_calendar_state_roundtrips():
    uid = str(uuid.uuid4())
    verify_state(issue_state(uid), expected_user_id=uid)  # no raise


def test_forged_state_rejected():
    with pytest.raises(OAuthStateError):
        verify_state("not.a.jwt", expected_user_id=str(uuid.uuid4()))


def test_expired_state_rejected(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "CALENDAR_OAUTH_STATE_TTL_SECONDS", -10)
    tok = issue_state(str(uuid.uuid4()))
    with pytest.raises(OAuthStateError):
        verify_state(tok, expected_user_id=str(uuid.uuid4()))


def test_state_wrong_user_rejected():
    tok = issue_state(str(uuid.uuid4()))
    with pytest.raises(OAuthStateError, match="does not match"):
        verify_state(tok, expected_user_id=str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# Exchange endpoint: rejects a replayed Gmail state; stores encrypted on success
# ---------------------------------------------------------------------------
def test_exchange_rejects_gmail_state(client, db, user1, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "GMAIL_OAUTH_STATE_SECRET", "unit-test-secret")
    gmail_token = gmail_state.issue_state(str(user1.id))
    tok = mint_supabase_token(sub=str(user1.id))
    resp = client.post("/calendar/oauth/exchange",
                       json={"code": "x", "state": gmail_token}, headers=_auth(tok))
    assert resp.status_code == 400
    # No account row was created from the rejected exchange.
    assert db.query(CalendarAccount).filter(CalendarAccount.user_id == user1.id).count() == 0


def test_exchange_stores_encrypted_tokens(client, db, user1, monkeypatch):
    good_state = issue_state(str(user1.id))

    class _Resp:
        def raise_for_status(self): ...
        def json(self):
            return {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600,
                    "scope": "https://www.googleapis.com/auth/calendar.events.readonly"}

    monkeypatch.setattr("app.api.routes.calendar_oauth.httpx.post", lambda *a, **k: _Resp())
    tok = mint_supabase_token(sub=str(user1.id))
    resp = client.post("/calendar/oauth/exchange",
                       json={"code": "authcode", "state": good_state}, headers=_auth(tok))
    assert resp.status_code == 200 and resp.json()["connected"] is True

    row = db.query(CalendarAccount).filter(CalendarAccount.user_id == user1.id).one()
    # Stored ciphertext, never plaintext.
    assert row.access_token.startswith("v1:") and "AT" not in row.access_token
    assert row.refresh_token.startswith("v1:") and "RT" not in row.refresh_token


def test_status_reflects_connection(client, db, user1):
    tok = mint_supabase_token(sub=str(user1.id))
    assert client.get("/calendar/oauth/status", headers=_auth(tok)).json()["connected"] is False
    _seed_connected(db, user1)
    assert client.get("/calendar/oauth/status", headers=_auth(tok)).json()["connected"] is True


def test_disconnect_revokes_and_wipes(client, db, user1, monkeypatch):
    _seed_connected(db, user1)
    revoked = {"called": False}
    monkeypatch.setattr("app.api.routes.calendar_oauth.httpx.post",
                        lambda *a, **k: revoked.__setitem__("called", True))
    tok = mint_supabase_token(sub=str(user1.id))
    resp = client.post("/calendar/oauth/disconnect", headers=_auth(tok))
    assert resp.status_code == 200 and resp.json()["connected"] is False
    assert revoked["called"] is True  # grant revoked at Google
    assert db.query(CalendarAccount).filter(CalendarAccount.user_id == user1.id).count() == 0


def test_endpoints_require_auth(client):
    assert client.get("/calendar/oauth/status").status_code in (401, 403)
    assert client.get("/calendar/today").status_code in (401, 403)


def test_calendar_today_caches_in_process(client, db, user1, monkeypatch):
    """Second rapid request is served from the ephemeral per-user cache — Google
    is hit once, not per mount. Nothing is written to the DB."""
    import app.api.routes.calendar as cal_route
    _seed_connected(db, user1)
    cal_route._today_cache.clear()
    calls = {"n": 0}

    def fake_fetch(acct, s):
        calls["n"] += 1
        return [CalendarEvent("Client review", datetime.now(timezone.utc), None, "office", False)]

    monkeypatch.setattr(cal_route, "fetch_today_events", fake_fetch)
    tok = mint_supabase_token(sub=str(user1.id))

    r1 = client.get("/calendar/today", headers=_auth(tok))
    r2 = client.get("/calendar/today", headers=_auth(tok))
    assert r1.json()["events"][0]["summary"] == "Client review"
    assert r2.json() == r1.json()
    assert calls["n"] == 1  # cached: Google not re-hit


def test_calendar_today_cache_expires(client, db, user1, monkeypatch):
    import app.api.routes.calendar as cal_route
    from app.core.config import settings
    monkeypatch.setattr(settings, "CALENDAR_TODAY_CACHE_TTL_SECONDS", -1)  # always stale
    _seed_connected(db, user1)
    cal_route._today_cache.clear()
    calls = {"n": 0}
    monkeypatch.setattr(cal_route, "fetch_today_events",
                        lambda a, s: (calls.__setitem__("n", calls["n"] + 1) or []))
    tok = mint_supabase_token(sub=str(user1.id))
    client.get("/calendar/today", headers=_auth(tok))
    client.get("/calendar/today", headers=_auth(tok))
    assert calls["n"] == 2  # TTL expired → refetched


def test_calendar_today_not_connected_uncached(client, db, user1):
    """A not-connected result is cheap and must NOT be cached (so a fresh connect
    shows up next mount)."""
    import app.api.routes.calendar as cal_route
    cal_route._today_cache.clear()
    tok = mint_supabase_token(sub=str(user1.id))
    assert client.get("/calendar/today", headers=_auth(tok)).json()["connected"] is False
    assert user1.id not in cal_route._today_cache


# ---------------------------------------------------------------------------
# Per-user scoping + the RLS-scoped read path (GRANT-enabled on Postgres)
# ---------------------------------------------------------------------------
def test_assemble_calendar_scoped_per_user(db, user1, user2, monkeypatch):
    _seed_connected(db, user1)  # only user1 is connected
    monkeypatch.setattr(stylist_cal, "fetch_events", lambda acct, s, **kw: [])
    assert assemble_calendar(db, user1.id).connected is True
    # user2 has no row → not connected (app-level filter; RLS backstops on PG).
    assert assemble_calendar(db, user2.id).connected is False


def test_assemble_calendar_under_rls_scoped_session(db, user1, monkeypatch):
    """The stylist reads calendar_accounts on the RLS-scoped connection. On
    Postgres this SELECT only succeeds because migration 0027 GRANTs the
    authenticated role table access; on SQLite the scope helper degrades to a
    plain session. Either way the read path must return the connected account."""
    from app.services.stylist.rls import rls_scoped_session
    _seed_connected(db, user1)
    monkeypatch.setattr(
        stylist_cal, "fetch_events",
        lambda acct, s, **kw: [CalendarEvent("Client review", datetime.now(timezone.utc), None, "office", False)],
    )
    with rls_scoped_session(user1.id) as sdb:
        block = assemble_calendar(sdb, user1.id, no_persist=False)
    assert block.connected is True and block.available is True
    assert block.formality_target == 4  # "review"/"office" → work


def test_incognito_reads_no_calendar(db, user1, monkeypatch):
    _seed_connected(db, user1)
    called = {"n": 0}
    monkeypatch.setattr(stylist_cal, "fetch_events",
                        lambda acct, s, **kw: called.__setitem__("n", called["n"] + 1) or [])
    block = assemble_calendar(db, user1.id, no_persist=True)
    assert block.connected is False and called["n"] == 0  # zero trace


# ---------------------------------------------------------------------------
# Dress-context derivation (pure)
# ---------------------------------------------------------------------------
def _ev(summary, location=None):
    return CalendarEvent(summary, datetime.now(timezone.utc), None, location, False)


def test_derive_dress_context_picks_dressiest():
    ctx = derive_dress_context([_ev("Gym session"), _ev("Client review", "office"), _ev("Coffee")])
    assert ctx.formality_target == 4 and ctx.occasion == "work"


def test_derive_dress_context_formal_wins():
    ctx = derive_dress_context([_ev("Team standup"), _ev("Cousin's wedding")])
    assert ctx.formality_target == 5


def test_derive_dress_context_none():
    assert derive_dress_context([_ev("xyzzy"), _ev("blorp")]).formality_target is None


# ---------------------------------------------------------------------------
# compose_outfit consumes the calendar-derived dress context
# ---------------------------------------------------------------------------
def _ctx(db, user, calendar=None):
    return ToolContext(db=db, user_id=user.id, profile=ProfileBlock(facts={}), calendar=calendar)


def test_compose_outfit_uses_calendar_when_unspecified(db, user1, monkeypatch):
    import app.services.stylist.tools as tools_mod
    captured = {}

    def fake_compose(db_, uid, profile, **kw):
        captured.update(kw)
        from app.services.stylist.composer import ComposedOutfit
        return ComposedOutfit()

    monkeypatch.setattr(tools_mod, "compose_outfit", fake_compose)
    monkeypatch.setattr(tools_mod, "forecast_for_facts", lambda facts: None)  # no weather

    cal = CalendarBlock(connected=True, events=[_ev("Client review", "office")],
                        occasion="work", formality_target=4)
    result = dispatch_tool(_ctx(db, user1, calendar=cal), "compose_outfit", {})
    assert captured["occasion"] == "work"
    assert captured["formality_target"] == 4
    assert result["calendar"]["derived_formality"] == 4


def test_compose_outfit_explicit_beats_calendar(db, user1, monkeypatch):
    import app.services.stylist.tools as tools_mod
    captured = {}

    def fake_compose(db_, uid, profile, **kw):
        captured.update(kw)
        from app.services.stylist.composer import ComposedOutfit
        return ComposedOutfit()

    monkeypatch.setattr(tools_mod, "compose_outfit", fake_compose)
    monkeypatch.setattr(tools_mod, "forecast_for_facts", lambda facts: None)

    cal = CalendarBlock(connected=True, events=[_ev("Wedding")],
                        occasion="a formal event", formality_target=5)
    result = dispatch_tool(_ctx(db, user1, calendar=cal),
                           "compose_outfit", {"occasion": "gym", "formality": 1})
    assert captured["occasion"] == "gym" and captured["formality_target"] == 1
    assert "calendar" not in result  # nothing was derived


# ---------------------------------------------------------------------------
# Multi-day, date-labeled context: today's events must not be misattributed to
# another day, and a request for a specific day derives from THAT day.
# ---------------------------------------------------------------------------
def _ev_on(day: date, summary, hour=10, location=None):
    start = datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)
    return CalendarEvent(summary, start, None, location, False)


def _today_tomorrow_block():
    """today = casual gym (A), tomorrow = a wedding (B). occasion/formality are
    TODAY's derived default, exactly as assemble_calendar builds it."""
    today = datetime.now(timezone.utc).date()
    tomorrow = today + timedelta(days=1)
    events = [_ev_on(today, "Gym session"), _ev_on(tomorrow, "Cousin's wedding")]
    today_ctx = derive_dress_context([events[0]])
    return CalendarBlock(connected=True, events=events,
                         occasion=today_ctx.occasion,
                         formality_target=today_ctx.formality_target), today, tomorrow


def test_prompt_text_labels_every_day():
    block, today, tomorrow = _today_tomorrow_block()
    text = block.to_prompt_text()
    assert "(today)" in text and "(tomorrow)" in text
    assert f"{today:%a %b} {today.day}" in text
    assert f"{tomorrow:%a %b} {tomorrow.day}" in text
    # both events carried, each under its own day
    assert "Gym session" in text and "Cousin's wedding" in text
    # today's derived line reflects today's (casual) event, not tomorrow's wedding
    assert "5/5" not in text


def test_dress_context_for_targets_named_day():
    block, today, tomorrow = _today_tomorrow_block()
    # tomorrow → the wedding (formality 5), NOT today's gym
    tmr = block.dress_context_for("tomorrow")
    assert tmr.formality_target == 5 and tmr.occasion == "a formal event"
    # ambiguous → today's gym default
    default = block.dress_context_for(None)
    assert default.formality_target == 1


def test_compose_outfit_tomorrow_uses_tomorrows_events(db, user1, monkeypatch):
    import app.services.stylist.tools as tools_mod
    captured = {}

    def fake_compose(db_, uid, profile, **kw):
        captured.update(kw)
        from app.services.stylist.composer import ComposedOutfit
        return ComposedOutfit()

    monkeypatch.setattr(tools_mod, "compose_outfit", fake_compose)
    monkeypatch.setattr(tools_mod, "forecast_for_facts", lambda facts: None)

    block, _today, _tomorrow = _today_tomorrow_block()
    result = dispatch_tool(_ctx(db, user1, calendar=block),
                           "compose_outfit", {"target_day": "tomorrow"})
    # occasion/formality come from TOMORROW's wedding (5), not today's gym (1)
    assert captured["formality_target"] == 5
    assert captured["occasion"] == "a formal event"
    assert result["calendar"]["for_day"] == "tomorrow"


def test_resolve_target_date():
    today = date(2026, 7, 8)  # a Wednesday
    assert resolve_target_date("today", today=today) == today
    assert resolve_target_date("tomorrow", today=today) == date(2026, 7, 9)
    assert resolve_target_date("2026-07-15", today=today) == date(2026, 7, 15)
    assert resolve_target_date("friday", today=today) == date(2026, 7, 10)
    assert resolve_target_date("wednesday", today=today) == today  # same-day weekday
    assert resolve_target_date("someday", today=today) is None
    assert resolve_target_date(None, today=today) is None
