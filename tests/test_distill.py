"""Wave S3 learning core: chat distillation + confidence decay + recompute.

Real behavior (no live LLM): the miner / narrative provider is faked to return a
typed structured-output object, exactly like google-genai's `.parsed`. Everything
else — signal writes, decay math, recompute precedence, cross-user isolation — runs
against the real SQLite substrate.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import Base, SessionLocal, engine
from app.models import (
    ChatMessage,
    Conversation,
    PreferenceSignal,
    StylePreference,
    StyleProfile,
    User,
)
from app.services.stylist import distill
from app.services.stylist.distill import (
    DistillOutput,
    MinedSignal,
    _Narrative,
    decay_preferences,
    recompute_preferences,
    run_chat_distill,
    run_redistill,
)


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _armed(monkeypatch):
    # distill_armed() needs a key + the feature flag; tests never hit the network.
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "DISTILL_ENABLED", True)


@pytest.fixture
def user1(db: Session):
    u = User(email="s3a@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture
def user2(db: Session):
    u = User(email="s3b@example.com", hashed_password="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


class FakeProvider:
    """Returns a canned typed object per response_schema, with real usage_metadata."""

    def __init__(self, by_schema):
        self.by_schema = by_schema
        self.calls = 0

    def generate_structured(self, *, response_schema, **kw):
        self.calls += 1
        return SimpleNamespace(
            parsed=self.by_schema[response_schema],
            text=None,
            usage_metadata=SimpleNamespace(
                prompt_token_count=1500, candidates_token_count=200
            ),
        )


def _conversation(db, user, *, user_msgs, assistant_msgs=()):
    conv = Conversation(user_id=user.id, title="t")
    db.add(conv); db.flush()
    for content in user_msgs:
        db.add(ChatMessage(conversation_id=conv.id, user_id=user.id,
                           role="user", content=content))
    for content in assistant_msgs:
        db.add(ChatMessage(conversation_id=conv.id, user_id=user.id,
                           role="assistant", content=content))
    db.commit()
    return conv


# ---------------------------------------------------------------------------
# Pass 1: chat distillation
# ---------------------------------------------------------------------------
def test_chat_distill_writes_positive_and_negative_signals(db, user1):
    conv = _conversation(
        db, user1,
        user_msgs=["I love earth-tone colors but I hate skinny jeans."],
        assistant_msgs=["Got it — warm palette, relaxed cuts."],
    )
    provider = FakeProvider({
        DistillOutput: DistillOutput(
            signals=[
                MinedSignal(dimension="color", polarity="like", strength=0.9,
                            note="earth tones"),
                MinedSignal(dimension="silhouette", polarity="dislike", strength=0.85,
                            note="skinny jeans"),
            ],
            session_summary="User discussed color palette and disliked skinny fits.",
        )
    })

    stats = run_chat_distill(db, user1.id, conv.id, provider=provider)
    db.commit()

    assert stats.signals_written == 2
    assert stats.summary_written is True

    sigs = (
        db.query(PreferenceSignal)
        .filter(PreferenceSignal.user_id == user1.id,
                PreferenceSignal.signal_type == "chat_distilled")
        .all()
    )
    by_dim = {s.key: s for s in sigs}
    assert by_dim["color"].polarity == "like"
    assert by_dim["silhouette"].polarity == "dislike"
    # Provenance is forced — a distilled signal is always 'chat_inferred'.
    assert all(s.source == "chat_inferred" for s in sigs)
    assert by_dim["color"].weight == pytest.approx(0.9)

    # The episodic session summary is its own typed row (not a preference).
    summary = (
        db.query(PreferenceSignal)
        .filter(PreferenceSignal.user_id == user1.id,
                PreferenceSignal.signal_type == "session_summary")
        .one()
    )
    assert "skinny" in summary.value["summary"]
    assert stats.cost_usd > 0.0  # priced from real usage_metadata


def test_chat_distill_never_raises_on_miner_failure(db, user1):
    conv = _conversation(db, user1, user_msgs=["hey"])

    class Broken:
        def generate_structured(self, **kw):
            raise RuntimeError("boom")

    stats = run_chat_distill(db, user1.id, conv.id, provider=Broken())
    assert stats.signals_written == 0
    assert stats.skipped_reason == "mine_failed"


def test_chat_distill_skips_when_no_user_content(db, user1):
    conv = _conversation(db, user1, user_msgs=[""], assistant_msgs=["hello"])
    provider = FakeProvider({DistillOutput: DistillOutput(signals=[])})
    stats = run_chat_distill(db, user1.id, conv.id, provider=provider)
    assert stats.skipped_reason == "no_user_content"
    assert provider.calls == 0  # never spent a model call


def test_chat_distill_caps_signal_volume(db, user1, monkeypatch):
    monkeypatch.setattr(settings, "DISTILL_MAX_SIGNALS_PER_SESSION", 2)
    conv = _conversation(db, user1, user_msgs=["lots of tastes"])
    provider = FakeProvider({
        DistillOutput: DistillOutput(signals=[
            MinedSignal(dimension="color", polarity="like"),
            MinedSignal(dimension="fit", polarity="like"),
            MinedSignal(dimension="brand", polarity="dislike"),
            MinedSignal(dimension="vibe", polarity="like"),
        ])
    })
    stats = run_chat_distill(db, user1.id, conv.id, provider=provider)
    assert stats.signals_written == 2


# ---------------------------------------------------------------------------
# Pass 1b: dirty-session sweep — distill each ENDED conversation ONCE (cost cut #4)
# ---------------------------------------------------------------------------
def _age_conversation(db, conv, *, minutes):
    """Force conv.updated_at into the past WITHOUT tripping the onupdate default."""
    past = datetime.utcnow() - timedelta(minutes=minutes)
    db.query(Conversation).filter(Conversation.id == conv.id).update(
        {Conversation.updated_at: past}, synchronize_session=False
    )
    db.commit()


def _patch_sweep_provider(monkeypatch, provider):
    import app.platform.ai_provider as ai
    monkeypatch.setattr(ai, "get_ai_provider", lambda: provider)


def _distill_output():
    return DistillOutput(
        signals=[MinedSignal(dimension="color", polarity="like", strength=0.8, note="navy")],
        session_summary="Talked about a navy palette.",
    )


def test_sweep_distills_idle_dirty_session_exactly_once(db, user1, monkeypatch):
    conv = _conversation(db, user1, user_msgs=["I love navy."],
                         assistant_msgs=["Noted — navy it is."])
    _age_conversation(db, conv, minutes=60)  # idle (> DISTILL_SESSION_IDLE_MINUTES)
    provider = FakeProvider({DistillOutput: _distill_output()})
    _patch_sweep_provider(monkeypatch, provider)

    from app.services.stylist.distill import run_distill_sweep

    stats = run_distill_sweep(db, user1.id)
    assert stats.sessions_idle == 1 and stats.sessions_distilled == 1
    assert stats.signals_written == 1
    assert provider.calls == 1  # ONE miner call for the whole session, not per turn

    # A second sweep sees the advanced marker -> nothing dirty -> no re-mine, no re-cost.
    stats2 = run_distill_sweep(db, user1.id)
    assert stats2.sessions_distilled == 0
    assert provider.calls == 1  # unchanged — distillation fired exactly once


def test_sweep_skips_the_active_conversation(db, user1, monkeypatch):
    conv = _conversation(db, user1, user_msgs=["still chatting"])
    _age_conversation(db, conv, minutes=60)
    provider = FakeProvider({DistillOutput: _distill_output()})
    _patch_sweep_provider(monkeypatch, provider)

    from app.services.stylist.distill import run_distill_sweep

    # The conversation the user is still in is excluded (session not over yet).
    stats = run_distill_sweep(db, user1.id, active_conversation_id=conv.id)
    assert stats.sessions_distilled == 0
    assert provider.calls == 0


def test_sweep_skips_recent_non_idle_conversation(db, user1, monkeypatch):
    _conversation(db, user1, user_msgs=["just now"])  # updated_at = now (not idle)
    provider = FakeProvider({DistillOutput: _distill_output()})
    _patch_sweep_provider(monkeypatch, provider)

    from app.services.stylist.distill import run_distill_sweep

    stats = run_distill_sweep(db, user1.id)
    assert stats.sessions_idle == 0 and stats.sessions_distilled == 0
    assert provider.calls == 0


def test_sweep_redistills_after_new_message_arrives(db, user1, monkeypatch):
    """A session reactivated by a new message becomes dirty again and is mined once more
    (no signals dropped): distillation is once-per-session, not once-forever."""
    conv = _conversation(db, user1, user_msgs=["first topic"])
    _age_conversation(db, conv, minutes=60)
    provider = FakeProvider({DistillOutput: _distill_output()})
    _patch_sweep_provider(monkeypatch, provider)

    from app.services.stylist.distill import run_distill_sweep

    assert run_distill_sweep(db, user1.id).sessions_distilled == 1
    assert provider.calls == 1

    # A new message lands AFTER the distillation (updated_at now > the distill marker),
    # so the session is dirty again. Use a future reference `now` so it still reads as
    # idle for the second sweep.
    reactivated = datetime.utcnow() + timedelta(seconds=5)
    db.add(ChatMessage(conversation_id=conv.id, user_id=user1.id,
                       role="user", content="second topic"))
    db.query(Conversation).filter(Conversation.id == conv.id).update(
        {Conversation.updated_at: reactivated}, synchronize_session=False)
    db.commit()

    later = datetime.utcnow() + timedelta(minutes=45)  # session has re-idled by `later`
    assert run_distill_sweep(db, user1.id, now=later).sessions_distilled == 1
    assert provider.calls == 2  # mined again for the new content


# ---------------------------------------------------------------------------
# Pass 2a: confidence decay
# ---------------------------------------------------------------------------
def test_decay_halves_confidence_over_one_halflife(db, user1, monkeypatch):
    monkeypatch.setattr(settings, "DISTILL_CONFIDENCE_HALFLIFE_DAYS", 30.0)
    now = datetime(2026, 7, 4, 12, 0, 0)
    db.add(StylePreference(
        user_id=user1.id, dimension="color", value={}, polarity="like",
        confidence=0.8, source="inferred", active=True,
        last_seen_at=now - timedelta(days=30),
    ))
    db.commit()

    decayed, deactivated = decay_preferences(db, user1.id, now)
    db.commit()

    row = db.query(StylePreference).filter_by(user_id=user1.id, dimension="color").one()
    assert decayed == 1
    assert row.confidence == pytest.approx(0.4, abs=0.01)  # 0.8 * exp(-ln2) = 0.4
    assert row.active is True  # 0.4 is above the floor


def test_decay_deactivates_stale_inferred_but_never_explicit(db, user1, monkeypatch):
    monkeypatch.setattr(settings, "DISTILL_CONFIDENCE_HALFLIFE_DAYS", 30.0)
    monkeypatch.setattr(settings, "DISTILL_ACTIVE_MIN_CONFIDENCE", 0.15)
    now = datetime(2026, 7, 4, 12, 0, 0)
    stale = now - timedelta(days=90)  # 3 half-lives -> factor 0.125
    db.add(StylePreference(user_id=user1.id, dimension="pattern", value={},
                           polarity="like", confidence=0.4, source="inferred",
                           active=True, last_seen_at=stale))
    db.add(StylePreference(user_id=user1.id, dimension="brand", value={},
                           polarity="dislike", confidence=0.4, source="explicit",
                           active=True, last_seen_at=stale))
    db.commit()

    _, deactivated = decay_preferences(db, user1.id, now)
    db.commit()

    inferred = db.query(StylePreference).filter_by(user_id=user1.id, dimension="pattern").one()
    explicit = db.query(StylePreference).filter_by(user_id=user1.id, dimension="brand").one()
    assert deactivated == 1
    assert inferred.active is False           # inferred decayed below floor -> dropped
    assert explicit.active is True            # user-stated taste is never auto-dropped
    assert explicit.confidence < 0.4          # ...but it still decays


# ---------------------------------------------------------------------------
# Pass 2b: recompute precedence (inferred never overwrites explicit)
# ---------------------------------------------------------------------------
def test_recompute_creates_inferred_preference_from_signals(db, user1):
    now = datetime(2026, 7, 4, 12, 0, 0)
    for _ in range(2):
        db.add(PreferenceSignal(user_id=user1.id, signal_type="chat_distilled",
                                key="silhouette", polarity="dislike", weight=0.9,
                                source="chat_inferred", created_at=now))
    db.commit()

    signals_seen, upserted, protected = recompute_preferences(db, user1.id, now)
    db.commit()

    row = db.query(StylePreference).filter_by(user_id=user1.id, dimension="silhouette").one()
    assert (signals_seen, upserted, protected) == (2, 1, 0)
    assert row.polarity == "dislike"
    assert row.source == "inferred"
    assert 0.0 < row.confidence <= settings.DISTILL_MAX_INFERRED_CONFIDENCE


def test_recompute_inferred_never_overwrites_explicit(db, user1):
    now = datetime(2026, 7, 4, 12, 0, 0)
    # User explicitly stated they LIKE this color palette.
    db.add(StylePreference(user_id=user1.id, dimension="color", value={"notes": ["earth"]},
                           polarity="like", confidence=0.9, source="explicit",
                           active=True, last_seen_at=now))
    # An inferred signal to the CONTRARY (they seemed to dislike it once).
    db.add(PreferenceSignal(user_id=user1.id, signal_type="chat_distilled",
                            key="color", polarity="dislike", weight=0.9,
                            source="chat_inferred", created_at=now))
    db.commit()

    _, upserted, protected = recompute_preferences(db, user1.id, now)
    db.commit()

    row = db.query(StylePreference).filter_by(user_id=user1.id, dimension="color").one()
    assert protected == 1
    assert upserted == 0
    assert row.polarity == "like"          # explicit statement stands
    assert row.confidence == pytest.approx(0.9)
    assert row.source == "explicit"


def test_recompute_explicit_signal_outranks_inferred_in_vote(db, user1):
    now = datetime(2026, 7, 4, 12, 0, 0)
    # One weak inferred 'dislike' vs one firm chat_explicit 'like' on the same axis.
    db.add(PreferenceSignal(user_id=user1.id, signal_type="chat_distilled",
                            key="formality", polarity="dislike", weight=0.6,
                            source="chat_inferred", created_at=now))
    db.add(PreferenceSignal(user_id=user1.id, signal_type="chat_stated",
                            key="formality", polarity="like", weight=0.9,
                            source="chat_explicit", created_at=now))
    db.commit()

    recompute_preferences(db, user1.id, now)
    db.commit()

    row = db.query(StylePreference).filter_by(user_id=user1.id, dimension="formality").one()
    assert row.polarity == "like"          # the user-stated vote wins the net
    assert row.source == "explicit"


# ---------------------------------------------------------------------------
# Cross-user isolation
# ---------------------------------------------------------------------------
def test_cross_user_isolation_in_redistill(db, user1, user2):
    now = datetime(2026, 7, 4, 12, 0, 0)
    db.add(PreferenceSignal(user_id=user1.id, signal_type="chat_distilled",
                            key="vibe", polarity="like", weight=0.9,
                            source="chat_inferred", created_at=now))
    db.commit()

    provider = FakeProvider({_Narrative: _Narrative(text="Leans minimalist.")})
    s1 = run_redistill(db, user1.id, now=now, provider=provider)
    s2 = run_redistill(db, user2.id, now=now, provider=provider)
    db.commit()

    # user1's signal produced exactly one preference, for user1 only.
    assert s1.prefs_upserted == 1
    assert s2.prefs_upserted == 0
    assert db.query(StylePreference).filter_by(user_id=user2.id).count() == 0
    assert db.query(StylePreference).filter_by(user_id=user1.id).count() == 1
    # user2 has no substrate — re-distill must not even create an empty profile row.
    assert db.query(StyleProfile).filter_by(user_id=user2.id).count() == 0


def test_chat_distill_isolates_writes_to_caller(db, user1, user2):
    conv = _conversation(db, user1, user_msgs=["I like linen in summer"])
    provider = FakeProvider({
        DistillOutput: DistillOutput(
            signals=[MinedSignal(dimension="material", polarity="like", strength=0.7)],
            session_summary="Talked about summer fabrics.",
        )
    })
    run_chat_distill(db, user1.id, conv.id, provider=provider)
    db.commit()

    assert db.query(PreferenceSignal).filter_by(user_id=user2.id).count() == 0
    assert db.query(PreferenceSignal).filter_by(user_id=user1.id).count() == 2


# ---------------------------------------------------------------------------
# Full nightly pass: decay + recompute + narrative
# ---------------------------------------------------------------------------
def test_run_redistill_regenerates_narrative_and_bumps_version(db, user1):
    now = datetime(2026, 7, 4, 12, 0, 0)
    db.add(StyleProfile(user_id=user1.id, facts={}, narrative_blob={}, version=1))
    db.add(PreferenceSignal(user_id=user1.id, signal_type="chat_distilled",
                            key="vibe", polarity="like", weight=0.9,
                            source="chat_inferred", created_at=now))
    db.commit()

    provider = FakeProvider({_Narrative: _Narrative(text="Leans clean and minimal.")})
    stats = run_redistill(db, user1.id, now=now, provider=provider)
    db.commit()

    profile = db.query(StyleProfile).filter_by(user_id=user1.id).one()
    assert stats.narrative_regenerated is True
    assert profile.narrative_blob["text"] == "Leans clean and minimal."
    assert profile.narrative_blob["source"] == "distilled"
    assert profile.version == 2
    assert profile.distilled_at == now


def test_run_redistill_never_raises_on_provider_failure(db, user1):
    now = datetime(2026, 7, 4, 12, 0, 0)
    db.add(PreferenceSignal(user_id=user1.id, signal_type="chat_distilled",
                            key="color", polarity="like", weight=0.9,
                            source="chat_inferred", created_at=now))
    db.commit()

    class Broken:
        def generate_structured(self, **kw):
            raise RuntimeError("model down")

    # Decay + recompute still land; only the narrative pass is skipped.
    stats = run_redistill(db, user1.id, now=now, provider=Broken())
    db.commit()
    assert stats.error is None
    assert stats.prefs_upserted == 1
    assert stats.narrative_regenerated is False
