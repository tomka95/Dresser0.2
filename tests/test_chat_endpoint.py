"""Wave S2 chat API: rate limit / quota / concurrency enforcement, SSE stream
integrity, persistence, and the full agent turn against a scripted provider."""

import json
import threading
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import Base, engine, SessionLocal
from app.models import ChatMessage, ChatUsage, ClothingItem, Conversation, User
from tests._authutil import mint_supabase_token
from app.services.stylist import limits
from app.services.stylist.limits import (
    QuotaExceeded,
    RateLimited,
    TooManyStreams,
    check_quota,
    check_rate_limit,
    record_turn_usage,
    stream_slot,
)
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
    u = User(email="chat1@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture
def user2(db: Session):
    u = User(email="chat2@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture
def tok1(user1):
    return mint_supabase_token(sub=str(user1.id))


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def _sse_events(response):
    """Parse an SSE body into (event, payload) tuples."""
    events = []
    for block in response.text.split("\n\n"):
        lines = [l for l in block.strip().splitlines() if l and not l.startswith(":")]
        if not lines:
            continue
        event = None
        data = None
        for line in lines:
            if line.startswith("event: "):
                event = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        if event:
            events.append((event, data))
    return events


# ---------------------------------------------------------------------------
# Limits (shared, DB-backed)
# ---------------------------------------------------------------------------
def test_rate_limit_enforced_within_window(db, user1):
    for _ in range(settings.CHAT_RATE_LIMIT_PER_MINUTE):
        check_rate_limit(db, user1.id)
    with pytest.raises(RateLimited):
        check_rate_limit(db, user1.id)


def test_rate_limit_window_resets(db, user1):
    from app.models import ChatRateWindow

    for _ in range(settings.CHAT_RATE_LIMIT_PER_MINUTE):
        check_rate_limit(db, user1.id)
    # Age the window past 60s -> next request starts a fresh window.
    row = db.query(ChatRateWindow).one()
    row.window_start = datetime.utcnow() - timedelta(seconds=61)
    db.commit()
    check_rate_limit(db, user1.id)  # must not raise


def test_rate_limit_is_per_user(db, user1, user2):
    for _ in range(settings.CHAT_RATE_LIMIT_PER_MINUTE):
        check_rate_limit(db, user1.id)
    check_rate_limit(db, user2.id)  # unaffected


def test_quota_turns_enforced(db, user1):
    db.add(ChatUsage(user_id=user1.id, period_start=datetime.utcnow().date(),
                     turns=settings.CHAT_DAILY_TURN_QUOTA, cost_usd=0))
    db.commit()
    with pytest.raises(QuotaExceeded):
        check_quota(db, user1.id)


def test_quota_cost_enforced(db, user1):
    db.add(ChatUsage(user_id=user1.id, period_start=datetime.utcnow().date(),
                     turns=1, cost_usd=settings.CHAT_DAILY_COST_QUOTA_USD))
    db.commit()
    with pytest.raises(QuotaExceeded):
        check_quota(db, user1.id)


def test_record_turn_usage_accumulates(db, user1):
    record_turn_usage(db, user1.id, input_tokens=100, output_tokens=20, cost_usd=0.002)
    record_turn_usage(db, user1.id, input_tokens=50, output_tokens=10, cost_usd=0.001)
    row = db.query(ChatUsage).filter_by(user_id=user1.id).one()
    assert row.turns == 2
    assert row.input_tokens == 150
    assert float(row.cost_usd) == pytest.approx(0.003)


def test_concurrency_cap_blocks_third_stream(db, user1):
    held = []
    release = threading.Event()
    acquired = threading.Barrier(settings.CHAT_MAX_CONCURRENT_STREAMS + 1)

    def hold():
        with stream_slot(user1.id):
            acquired.wait(timeout=5)
            release.wait(timeout=5)

    threads = [threading.Thread(target=hold)
               for _ in range(settings.CHAT_MAX_CONCURRENT_STREAMS)]
    for t in threads:
        t.start()
    acquired.wait(timeout=5)  # both slots held
    with pytest.raises(TooManyStreams):
        with stream_slot(user1.id):
            pass
    release.set()
    for t in threads:
        t.join(timeout=5)
    # slots released -> reusable
    with stream_slot(user1.id):
        pass


# ---------------------------------------------------------------------------
# Endpoint: auth + payload guards + limit responses
# ---------------------------------------------------------------------------
def test_chat_requires_auth(client, db):
    assert client.post("/chat", json={"message": "hi"}).status_code == 401


def test_chat_rejects_oversized_message(client, db, tok1):
    r = client.post("/chat", headers=_auth(tok1),
                    json={"message": "x" * (settings.CHAT_MAX_MESSAGE_CHARS + 1)})
    assert r.status_code == 422


def test_chat_rejects_too_many_attachments(client, db, user1, tok1):
    attachment = {"type": "closet_item", "itemId": str(uuid.uuid4())}
    r = client.post("/chat", headers=_auth(tok1), json={
        "message": "hi",
        "attachments": [attachment] * (settings.CHAT_MAX_ATTACHMENTS + 1),
    })
    assert r.status_code == 422


def test_chat_rejects_invalid_base64_image(client, db, tok1):
    r = client.post("/chat", headers=_auth(tok1), json={
        "message": "hi",
        "attachments": [{"type": "image", "dataBase64": "!!!notb64!!!",
                         "mimeType": "image/jpeg"}],
    })
    assert r.status_code == 422


def test_chat_returns_429_when_quota_exhausted(client, db, user1, tok1):
    db.add(ChatUsage(user_id=user1.id, period_start=datetime.utcnow().date(),
                     turns=settings.CHAT_DAILY_TURN_QUOTA))
    db.commit()
    r = client.post("/chat", headers=_auth(tok1), json={"message": "hi"})
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "quota_exceeded"


def test_chat_returns_429_when_rate_limited(client, db, user1, tok1, monkeypatch):
    monkeypatch.setattr(settings, "CHAT_RATE_LIMIT_PER_MINUTE", 1)
    calls = {"n": 0}

    def fake_turn(turn, emit):
        raise AssertionError("agent must not run when rate limited")

    import app.api.routes.chat as chat_route

    # First request consumes the single window slot (agent mocked to no-op).
    def ok_turn(turn, emit):
        from app.services.stylist.agent import TurnResult
        calls["n"] += 1
        return TurnResult(conversation_id=uuid.uuid4(), message_id=uuid.uuid4(),
                          text="", outfits=[], input_tokens=0, output_tokens=0,
                          cost_usd=0, model="m")

    monkeypatch.setattr(chat_route, "run_stylist_turn", ok_turn)
    assert client.post("/chat", headers=_auth(tok1), json={"message": "hi"}).status_code == 200

    monkeypatch.setattr(chat_route, "run_stylist_turn", fake_turn)
    r = client.post("/chat", headers=_auth(tok1), json={"message": "hi again"})
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "rate_limited"


# ---------------------------------------------------------------------------
# SSE stream integrity (scripted agent)
# ---------------------------------------------------------------------------
def test_sse_stream_orders_meta_token_tool_outfit_done(client, db, user1, tok1, monkeypatch):
    import app.api.routes.chat as chat_route
    from app.services.stylist.agent import TurnResult

    conv_id, msg_id = uuid.uuid4(), uuid.uuid4()

    def scripted_turn(turn, emit):
        emit("meta", {"conversationId": str(conv_id), "model": "gemini-2.5-flash"})
        emit("tool", {"name": "search_closet", "status": "started",
                      "label": "checking your closet…"})
        emit("tool", {"name": "search_closet", "status": "finished",
                      "label": "checking your closet…"})
        emit("outfit", {"slots": {}, "itemIds": [], "rationale": "r", "warnings": []})
        emit("token", {"text": "Hello "})
        emit("token", {"text": "there"})
        return TurnResult(conversation_id=conv_id, message_id=msg_id,
                          text="Hello there", outfits=[], input_tokens=42,
                          output_tokens=7, cost_usd=0.0011, model="gemini-2.5-flash")

    monkeypatch.setattr(chat_route, "run_stylist_turn", scripted_turn)

    r = client.post("/chat", headers=_auth(tok1), json={"message": "hi"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    events = _sse_events(r)
    names = [e for e, _ in events]
    assert names == ["meta", "tool", "tool", "outfit", "token", "token", "done"]
    done = events[-1][1]
    assert done["conversationId"] == str(conv_id)
    assert done["inputTokens"] == 42
    assert done["costUsd"] == pytest.approx(0.0011)

    # usage was rolled into the quota ledger
    row = db.query(ChatUsage).filter_by(user_id=user1.id).one()
    assert row.turns == 1 and row.input_tokens == 42


def test_sse_stream_emits_error_event_on_agent_failure(client, db, user1, tok1, monkeypatch):
    import app.api.routes.chat as chat_route

    def broken_turn(turn, emit):
        emit("meta", {"conversationId": str(uuid.uuid4()), "model": "m"})
        raise RuntimeError("model exploded")

    monkeypatch.setattr(chat_route, "run_stylist_turn", broken_turn)
    r = client.post("/chat", headers=_auth(tok1), json={"message": "hi"})
    assert r.status_code == 200  # stream already started; failure is an event
    events = _sse_events(r)
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "turn_failed"
    assert "model exploded" not in r.text  # internals never leak to the client


# ---------------------------------------------------------------------------
# Full turn against a scripted provider (real persistence + tools)
# ---------------------------------------------------------------------------
class _FakeStreamModels:
    """Scripted Gemini: one search_closet call, then a grounded reply."""

    def __init__(self):
        self.calls = 0

    def generate_content_stream(self, *, model, contents, config):
        from google.genai import types

        self.calls += 1
        if self.calls == 1:
            yield SimpleNamespace(
                candidates=[SimpleNamespace(content=SimpleNamespace(parts=[
                    SimpleNamespace(text=None, function_call=types.FunctionCall(
                        name="search_closet", args={"categories": ["top"]}))
                ]))],
                usage_metadata=SimpleNamespace(prompt_token_count=900,
                                               candidates_token_count=20),
            )
        else:
            yield SimpleNamespace(
                candidates=[SimpleNamespace(content=SimpleNamespace(parts=[
                    SimpleNamespace(text="Your white tee works great.",
                                    function_call=None)
                ]))],
                usage_metadata=SimpleNamespace(prompt_token_count=1200,
                                               candidates_token_count=30),
            )

    def generate_content(self, *, model, contents, config):
        # Flash-Lite pre-parse: default intent, no escalation.
        return SimpleNamespace(
            parsed={"intent": "question", "deep_reasoning_requested": False,
                    "references_attached_image": False,
                    "injection_suspected": False},
            text="{}",
            usage_metadata=SimpleNamespace(prompt_token_count=300,
                                           candidates_token_count=10),
        )


def test_full_turn_persists_transcript_and_cost(db, user1, monkeypatch):
    from app.platform.ai_provider import AIProvider
    import app.platform.ai_provider as provider_module
    from app.services.stylist.agent import TurnRequest, run_stylist_turn

    db.add(ClothingItem(user_id=user1.id, name="White Tee", category="top"))
    db.commit()

    fake = AIProvider.__new__(AIProvider)
    fake._provider = "gemini"
    fake._client = SimpleNamespace(models=_FakeStreamModels())
    monkeypatch.setattr(provider_module, "get_ai_provider", lambda: fake)

    emitted = []
    result = run_stylist_turn(
        TurnRequest(user_id=user1.id, message="what tops do I own?"),
        emit=lambda e, p: emitted.append((e, p)),
    )

    assert result.text == "Your white tee works great."
    # Two Flash rounds only — the hot path no longer spends a Flash-Lite pre-parse
    # round-trip (routing is now a local keyword heuristic), so its 300/10 tokens
    # are gone from the turn total.
    assert result.input_tokens == 900 + 1200
    assert result.output_tokens == 20 + 30
    assert result.cost_usd > 0

    conv = db.query(Conversation).one()
    assert conv.user_id == user1.id
    messages = db.query(ChatMessage).order_by(ChatMessage.created_at).all()
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].content == "what tops do I own?"
    assert messages[1].content == "Your white tee works great."
    assert messages[1].input_tokens == 2100
    assert float(messages[1].cost_usd) == pytest.approx(result.cost_usd)
    assert messages[1].tool_calls[0]["name"] == "search_closet"

    names = [e for e, _ in emitted]
    assert names[0] == "meta"
    assert ("tool" in names) and ("token" in names)


def test_full_turn_second_message_reuses_conversation(db, user1, monkeypatch):
    from app.platform.ai_provider import AIProvider
    import app.platform.ai_provider as provider_module
    from app.services.stylist.agent import TurnRequest, run_stylist_turn

    fake = AIProvider.__new__(AIProvider)
    fake._provider = "gemini"
    fake._client = SimpleNamespace(models=_FakeStreamModels())
    monkeypatch.setattr(provider_module, "get_ai_provider", lambda: fake)

    first = run_stylist_turn(TurnRequest(user_id=user1.id, message="hi"),
                             emit=lambda e, p: None)
    fake._client = SimpleNamespace(models=_FakeStreamModels())
    second = run_stylist_turn(
        TurnRequest(user_id=user1.id, message="and again",
                    conversation_id=first.conversation_id),
        emit=lambda e, p: None,
    )
    assert second.conversation_id == first.conversation_id
    assert db.query(Conversation).count() == 1
    assert db.query(ChatMessage).count() == 4


def test_incognito_turn_writes_no_conversation_or_messages(db, user1, monkeypatch):
    """Incognito guarantee: the turn runs to completion but persists NOTHING —
    zero conversation rows, zero message rows. Nothing left for distillation."""
    from app.platform.ai_provider import AIProvider
    import app.platform.ai_provider as provider_module
    from app.services.stylist.agent import TurnRequest, run_stylist_turn

    db.add(ClothingItem(user_id=user1.id, name="White Tee", category="top"))
    db.commit()

    fake = AIProvider.__new__(AIProvider)
    fake._provider = "gemini"
    fake._client = SimpleNamespace(models=_FakeStreamModels())
    monkeypatch.setattr(provider_module, "get_ai_provider", lambda: fake)

    result = run_stylist_turn(
        TurnRequest(user_id=user1.id, message="what tops do I own?", no_persist=True),
        emit=lambda e, p: None,
    )

    # The turn ran (model replied, tokens counted)...
    assert result.text == "Your white tee works great."
    assert result.input_tokens == 900 + 1200
    # ...but left ZERO transcript trace in the DB.
    assert db.query(Conversation).count() == 0
    assert db.query(ChatMessage).count() == 0


def test_conversation_history_endpoints_are_tenant_scoped(client, db, user1, user2, tok1):
    other_conv = Conversation(user_id=user2.id, title="theirs")
    db.add(other_conv); db.commit()

    r = client.get("/chat/conversations", headers=_auth(tok1))
    assert r.status_code == 200
    assert r.json()["conversations"] == []  # user2's thread invisible

    r = client.get(f"/chat/conversations/{other_conv.id}/messages", headers=_auth(tok1))
    assert r.status_code == 200
    assert r.json()["messages"] == []  # tenant-filtered, no oracle


def test_delete_conversation_removes_own_and_cascades_messages(client, db, user1, tok1):
    conv = Conversation(user_id=user1.id, title="mine")
    db.add(conv); db.flush()
    db.add(ChatMessage(conversation_id=conv.id, user_id=user1.id, role="user",
                       content="hi"))
    db.commit()
    conv_id = conv.id

    r = client.delete(f"/chat/conversations/{conv_id}", headers=_auth(tok1))
    assert r.status_code == 200
    assert r.json() == {"deleted": True}
    assert db.query(Conversation).filter_by(id=conv_id).count() == 0
    assert db.query(ChatMessage).filter_by(conversation_id=conv_id).count() == 0  # cascade


def test_delete_conversation_cannot_touch_another_users_thread(client, db, user1, user2, tok1):
    other_conv = Conversation(user_id=user2.id, title="theirs")
    db.add(other_conv); db.commit()

    r = client.delete(f"/chat/conversations/{other_conv.id}", headers=_auth(tok1))
    assert r.status_code == 200
    assert r.json() == {"deleted": False}  # no oracle, and no deletion
    assert db.query(Conversation).filter_by(id=other_conv.id).count() == 1  # intact
