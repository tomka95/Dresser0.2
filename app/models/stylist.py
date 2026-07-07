"""AI Stylist substrate + chat models.

Wave S0/S1/S3 preference substrate (item_embeddings, style_events, style_profiles,
style_preferences, preference_signals) and Wave S2 chat vertical (conversations,
chat_messages, saved_outfits, chat_usage, chat_rate_windows).

Split out of the former monolithic app/models.py (P3.2, ARCHITECTURE_AUDIT R4).
Re-exported from app.models for backward compatibility -- see
app/models/__init__.py.

All user-facing tables carry UUID user_id -> users(id) and per-user RLS
(auth.uid() = user_id) applied in their owning migration (0018 / 0020); RLS is
not expressible in the ORM. The legacy user_preferences / user_preference_events
(TEXT user_id, 0 rows, no live reader/writer) were dropped in 0018 and are
SUPERSEDED by style_preferences / preference_signals. chat_rate_windows is
server-managed (RLS enabled, no policies).
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    REAL, BigInteger, Boolean, CheckConstraint, Column, Date, ForeignKey, Index,
    Integer, Numeric, Text, UniqueConstraint, text,
)
from sqlalchemy.orm import relationship

from app.db import Base, GUID
from app.models._shared import _jsonb, _tstz, _uuid_array, _vector


# --- AI Stylist substrate (Wave S0, migration 0018) --------------------------
# Foundation tables the Stylist writes through in later branches (B: enrichment /
# item_embeddings; C: style_events; S1: style_profiles distillation).

class ItemEmbedding(Base):
    """pgvector embedding for a clothing item.

    Side table (not a column on clothing_items) so re-embedding / model-versioning
    never touches the hot closet row and the ANN index lives on a dedicated relation.
    Branch B populates rows and builds the hnsw/ivfflat index post-load; nothing in
    Branch A writes here. user_id is denormalized from the parent item so RLS filters
    without a join.
    """

    __tablename__ = "item_embeddings"

    __table_args__ = (
        UniqueConstraint("item_id", "model", "version",
                         name="item_embeddings_item_id_model_version_key"),
        Index("idx_item_embeddings_user_id", "user_id"),
        # ANN index (Branch B, migration 0019) — built now that enrichment can bulk-
        # populate. hnsw + cosine for semantic closet retrieval. Declared here AND created
        # in 0019 (mirrors the live GIN pattern) so `alembic check` matches it by name and
        # stays green. postgresql_using/ops are honored on Postgres; on the SQLite dev path
        # the vector column is a Text fallback and this degrades to a plain index.
        Index(
            "idx_item_embeddings_embedding_hnsw", "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    item_id = Column(GUID(), ForeignKey("clothing_items.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # Dimension fixed at DDL time (config.EMBEDDING_DIM, default 768 = gemini-embedding-001
    # truncated via output_dimensionality/MRL). Changing the dim requires re-migrating this column.
    embedding = Column(_vector(768), nullable=False)
    model = Column(Text, nullable=False)
    dim = Column(Integer, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)
    updated_at = Column(_tstz(), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class StyleEvent(Base):
    """Interaction event log for the AI Stylist (Branch C writes).

    Per-event detail (dwell_ms, reason_chips, feed_position, weather, occasion, ...)
    lives under the `properties` jsonb — no dedicated columns for those.
    """

    __tablename__ = "style_events"

    __table_args__ = (
        # created_at DESC live (recent-first). text() keeps metadata == reflection.
        Index("idx_style_events_user_created_at", "user_id", text('created_at DESC')),
        Index("idx_style_events_user_event_type", "user_id", "event_type"),
        Index("idx_style_events_item_id", "item_id"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(Text, nullable=False)
    # SET NULL: deleting an item must not erase the interaction history.
    item_id = Column(GUID(), ForeignKey("clothing_items.id", ondelete="SET NULL"), nullable=True)
    entity_type = Column(Text, nullable=True)
    entity_id = Column(Text, nullable=True)
    source = Column(Text, nullable=True)
    properties = Column(_jsonb(), nullable=False, default=dict)
    session_id = Column(GUID(), nullable=True)
    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)


class StyleProfile(Base):
    """Distilled per-user style profile (one row per user; S1 re-distills).

    `facts` = L1 hard constraints/sizes (inviolable, cheaply + separately readable by
    the outfit composer); `narrative_blob` = the distilled prose profile; `summary` =
    short headline. Facts and narrative are distinct concerns -> distinct columns.
    """

    __tablename__ = "style_profiles"

    __table_args__ = (
        UniqueConstraint("user_id", name="style_profiles_user_id_key"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    facts = Column(_jsonb(), nullable=False, default=dict)
    narrative_blob = Column(_jsonb(), nullable=False, default=dict)
    summary = Column(Text, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    distilled_at = Column(_tstz(), nullable=True)
    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)
    updated_at = Column(_tstz(), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class StylePreference(Base):
    """Structured per-user style preference (supersedes user_preferences).

    `dimension` = the preference axis (color/silhouette/formality/brand/...);
    `polarity` = like|dislike|neutral; `evidence_count` / `example_item_ids` back the
    preference with observed items; `evidence` is the free-text carrier flagged for
    future field-level redaction. last_seen_at doubles as last_reinforced_at.
    """

    __tablename__ = "style_preferences"

    __table_args__ = (
        UniqueConstraint("user_id", "dimension", name="style_preferences_user_id_dimension_key"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
                        name="confidence"),
        CheckConstraint("polarity IS NULL OR polarity IN ('like','dislike','neutral')",
                        name="polarity"),
        CheckConstraint("source IN ('explicit','inferred','onboarding','imported')",
                        name="source"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    dimension = Column(Text, nullable=False)
    value = Column(_jsonb(), nullable=False, default=dict)
    polarity = Column(Text, nullable=True)
    confidence = Column(REAL, nullable=True)
    weight = Column(REAL, nullable=True)
    evidence_count = Column(Integer, nullable=False, default=0)
    example_item_ids = Column(_uuid_array(), nullable=True)
    source = Column(Text, nullable=False, default="explicit")
    active = Column(Boolean, nullable=False, default=True)
    evidence = Column(Text, nullable=True)
    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)
    updated_at = Column(_tstz(), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_seen_at = Column(_tstz(), default=datetime.utcnow, nullable=False)


class PreferenceSignal(Base):
    """Raw signal feeding preference distillation (append-only; supersedes
    user_preference_events). May reference the style_event it derived from."""

    __tablename__ = "preference_signals"

    __table_args__ = (
        Index("idx_preference_signals_user_created_at", "user_id", text('created_at DESC')),
        Index("idx_preference_signals_user_signal_type", "user_id", "signal_type"),
        Index("idx_preference_signals_event_id", "event_id"),
        CheckConstraint("polarity IS NULL OR polarity IN ('like','dislike','neutral')",
                        name="polarity"),
        CheckConstraint(
            "source IS NULL OR source IN "
            "('onboarding','chat_explicit','chat_inferred','behavior','outfit_feedback')",
            name="source"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    signal_type = Column(Text, nullable=False)
    key = Column(Text, nullable=True)
    value = Column(_jsonb(), nullable=True)
    polarity = Column(Text, nullable=True)
    item_id = Column(GUID(), ForeignKey("clothing_items.id", ondelete="SET NULL"), nullable=True)
    event_id = Column(GUID(), ForeignKey("style_events.id", ondelete="SET NULL"), nullable=True)
    # Freeform pointer to the signal's origin (message_id / event_id / 'onboarding').
    evidence_ref = Column(Text, nullable=True)
    weight = Column(REAL, nullable=True)   # signal strength
    source = Column(Text, nullable=True)
    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)


# --- AI Stylist chat (Wave S2, migration 0020) --------------------------------
# The chat vertical: conversations + transcript + saved outfits + the usage/quota
# ledger + the shared rate-limiter state. All user-facing tables carry UUID
# user_id -> users(id) and per-user RLS (auth.uid() = user_id) applied in the
# migration; chat_rate_windows is server-managed (RLS enabled, no policies).


def _chat_expires_default():
    """Python-side rolling-retention default (server default owned by 0020)."""
    from datetime import timedelta

    from app.core.config import settings as _settings

    return datetime.utcnow() + timedelta(days=_settings.CHAT_RETENTION_DAYS)


class Conversation(Base):
    """One chat thread. expires_at is the retention TTL (rolling: every new
    message pushes it forward); the sweep deletes expired rows and CASCADE
    erases their messages."""

    __tablename__ = "conversations"

    __table_args__ = (
        Index("idx_conversations_user_id", "user_id"),
        Index("idx_conversations_expires_at", "expires_at"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(Text, nullable=True)
    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)
    updated_at = Column(_tstz(), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    expires_at = Column(_tstz(), default=_chat_expires_default, nullable=False)

    messages = relationship("ChatMessage", back_populates="conversation",
                            cascade="all, delete-orphan")


class ChatMessage(Base):
    """One transcript message. user_id is denormalized from the conversation
    (mirrors item_embeddings) so RLS filters without a join. Assistant rows carry
    the turn's token counts + cost (the per-turn cost ledger) and, when a tool
    composed an outfit, the outfit payload for history re-render."""

    __tablename__ = "chat_messages"

    __table_args__ = (
        Index("idx_chat_messages_conversation_created", "conversation_id", "created_at"),
        Index("idx_chat_messages_user_id", "user_id"),
        CheckConstraint("role IN ('user','assistant','tool')", name="role"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(GUID(), ForeignKey("conversations.id", ondelete="CASCADE"),
                             nullable=False)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(Text, nullable=False)
    content = Column(Text, nullable=False, default="")
    # [{name, status, latency_ms, summary}] — ids + counts only, never raw args.
    tool_calls = Column(_jsonb(), nullable=True)
    # Composed-outfit payload (item ids + slots + rationale) for assistant turns.
    outfit_json = Column(_jsonb(), nullable=True)
    model = Column(Text, nullable=True)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Numeric, nullable=False, default=0)
    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)

    conversation = relationship("Conversation", back_populates="messages")


class SavedOutfit(Base):
    """A composed outfit the user kept (compose_outfit -> save_outfit). item_ids
    reference the user's own clothing_items — ownership is validated server-side
    at save time (array FKs are not enforceable in Postgres)."""

    __tablename__ = "saved_outfits"

    __table_args__ = (
        Index("idx_saved_outfits_user_id", "user_id"),
        CheckConstraint("source IN ('chat','composer')", name="source"),
        # Feedback lifecycle (Wave S3, migration 0021). Named CHECK (not diffed by
        # autogenerate); server default 'active' owned by the migration.
        CheckConstraint(
            "status IN ('active','worn','rejected','archived')", name="status"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(Text, nullable=True)
    item_ids = Column(_uuid_array(), nullable=False)
    rationale = Column(Text, nullable=True)
    occasion = Column(Text, nullable=True)
    source = Column(Text, nullable=False, default="chat")

    # --- Wave S3 outfit feedback -> learning (migration 0021) --------------------
    # A kept outfit's lifecycle, driven by post-hoc feedback the user gives on the
    # composed outfit in chat:
    #   'active'   : saved, no terminal feedback yet (default)
    #   'worn'     : user reported wearing it (outfit_worn one-tap) — worn_at is set
    #   'rejected' : user rejected it after saving (outfit_reject)
    #   'archived' : hidden by the user
    # Named CHECK above; server default 'active' (migration 0021) backfills legacy rows.
    status = Column(Text, nullable=False, default="active")
    # When the user reported wearing this outfit (outfit_worn). NULL until then.
    worn_at = Column(_tstz(), nullable=True)
    # PII-free carrier for the LAST feedback applied to this outfit:
    # {feedback, reason_chips[], slot, direction{}, signals}. Never free text /
    # message content. NULL until the first feedback lands.
    feedback = Column(_jsonb(), nullable=True)

    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)


class ChatUsage(Base):
    """Per-user per-DAY usage rollup: turns, tokens, dollars. THE free-tier quota
    ledger (checked before every turn) — incremented via atomic upsert so it is
    correct across workers. Counts + dollars only, never message content."""

    __tablename__ = "chat_usage"

    __table_args__ = (
        UniqueConstraint("user_id", "period_start",
                         name="chat_usage_user_id_period_start_key"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    period_start = Column(Date, nullable=False)
    turns = Column(Integer, nullable=False, default=0)
    input_tokens = Column(BigInteger, nullable=False, default=0)
    output_tokens = Column(BigInteger, nullable=False, default=0)
    cost_usd = Column(Numeric, nullable=False, default=0)
    updated_at = Column(_tstz(), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ChatRateWindow(Base):
    """Fixed-window rate-limiter state (one row per user), mutated via atomic
    upsert so the limit holds across workers. Server-managed only: RLS is enabled
    with NO policies in the migration (anon/authenticated denied)."""

    __tablename__ = "chat_rate_windows"

    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    window_start = Column(_tstz(), nullable=False)
    count = Column(Integer, nullable=False, default=0)
