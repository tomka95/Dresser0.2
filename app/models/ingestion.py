"""Gmail + photo ingestion pipeline models.

google_accounts (Gmail OAuth token store), processed_messages / ingest_candidates
/ ingest_runs (Gmail phase 3a-3c), processed_uploads / photo_detect_sessions
(photo ingest, Wave 1/1.5).

Split out of the former monolithic app/models.py (P3.2, ARCHITECTURE_AUDIT R4).
Re-exported from app.models for backward compatibility -- see
app/models/__init__.py.

All carry per-user RLS (auth.uid() = user_id), applied by their owning
migration (0006 / 0014 / 0015); RLS is not expressible in the ORM. user_id is
UUID everywhere (no text + ::text cast).
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, BigInteger, Boolean, CheckConstraint, Date, ForeignKey, Index,
    Integer, Numeric, SmallInteger, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db import Base, GUID
from app.models._shared import _jsonb, _text_array, _tstz


class GoogleAccount(Base):

    __tablename__ = "google_accounts"

    __table_args__ = (
        UniqueConstraint("user_id", name="google_accounts_user_id_key"),
        Index("idx_google_accounts_email", "email"),
        Index("idx_google_accounts_google_sub", "google_sub"),
    )

    # Live column is bigint (bigserial).
    id = Column(BigInteger, primary_key=True, autoincrement=True)

    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Live: all of these are `text`.
    # google_sub / email are nullable as of migration 0005: the dedicated Gmail
    # ingest client requests gmail.readonly ONLY (no identity scopes), so the
    # connect flow has no Google subject id or email to record. Identity lives in
    # Supabase Auth; this table is purely the per-user Gmail token store.
    google_sub = Column(Text, nullable=True)

    email = Column(Text, nullable=True)

    # Stored ENCRYPTED at rest (AES-256-GCM, see app/core/token_crypto). Column
    # type is unchanged (text); only the contents are ciphertext now.
    access_token = Column(Text, nullable=False)

    refresh_token = Column(Text, nullable=True)

    scope = Column(Text, nullable=True)

    token_expiry = Column(_tstz(), nullable=True)

    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)

    updated_at = Column(_tstz(), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="google_account")


class CalendarAccount(Base):
    """Per-user Google Calendar OAuth token store (calendar.events.readonly).

    Separate from google_accounts on purpose: a distinct OAuth surface (distinct
    dedicated Google client + scope) gets its own token row, so connecting/
    disconnecting calendar never touches the Gmail grant. NO calendar content is
    ever stored here — events are read LIVE per request via CalendarOAuthClient.
    Only the OAuth tokens live here, ENCRYPTED at rest (AES-256-GCM,
    app/core/token_crypto); the columns are text holding `v1:` ciphertext.

    RLS (auth.uid() = user_id, 4-verb) + an explicit GRANT to the authenticated
    role are applied by migration 0027 (RLS is not expressible in the ORM; the
    GRANT is required because the RLS-scoped agent turn reads this row).
    """

    __tablename__ = "calendar_accounts"

    __table_args__ = (
        UniqueConstraint("user_id", name="calendar_accounts_user_id_key"),
    )

    # Live column is bigint (bigserial). SQLite only auto-increments a plain
    # INTEGER PRIMARY KEY, so map bigint on Postgres, Integer on the sqlite
    # dev/test path — keeps metadata matching the migration (bigserial) while
    # letting create_all() inserts get an id.
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)

    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Stored ENCRYPTED at rest (text columns holding `v1:` ciphertext).
    access_token = Column(Text, nullable=False)

    refresh_token = Column(Text, nullable=True)

    scope = Column(Text, nullable=True)

    token_expiry = Column(_tstz(), nullable=True)

    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)

    updated_at = Column(_tstz(), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


# --- Gmail->closet ingestion (phase 3a) --------------------------------------
# Foundation tables for the rebuilt ingestion pipeline (3b writes through these).
# All three carry per-user RLS (auth.uid() = user_id) applied in migration 0006;
# RLS is not expressible in the ORM and is owned by the migration. user_id is
# UUID everywhere (no text + ::text cast).

class ProcessedMessage(Base):
    """Per-(user, message) idempotency ledger: a Gmail message is processed once."""

    __tablename__ = "processed_messages"

    __table_args__ = (
        UniqueConstraint("user_id", "message_id",
                         name="processed_messages_user_id_message_id_key"),
        CheckConstraint(
            "status IN ('fetched','filtered_out','extracted','confirmed','rejected','error')",
            name="status",
        ),
        Index("idx_processed_messages_user_id", "user_id"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # The Gmail account that owned this message. Plain bigint (no FK) to mirror the
    # migration; provenance-only, not an integrity edge.
    google_account_id = Column(BigInteger, nullable=True)

    message_id = Column(Text, nullable=False)

    content_hash = Column(Text, nullable=True)

    status = Column(Text, nullable=False, default="fetched")

    # Clothing-likely-first extraction ordering (Feature A). 0 = likely (extract first),
    # 1 = other. Computed cheaply at fetch time (receipt_filter.clothing_priority).
    extract_priority = Column(SmallInteger, nullable=False, default=1)

    processed_at = Column(_tstz(), default=datetime.utcnow, nullable=False)


class IngestCandidate(Base):
    """Swipe-review staging row: a typed candidate item awaiting accept/reject."""

    __tablename__ = "ingest_candidates"

    __table_args__ = (
        CheckConstraint("status IN ('pending','accepted','rejected')", name="status"),
        CheckConstraint("currency IS NULL OR length(currency) = 3", name="currency"),
        # image_status lifecycle enum (named CHECK; not diffed by autogenerate).
        # Mirrors clothing_items.image_status (migration 0010) exactly. NULL allowed
        # for rows created before the column. Drives the streaming swipe deck (Phase 4):
        # 'resolved' = verified image present, 'pending' = still resolving (shimmer +
        # poll), 'placeholder' = slow tiers exhausted with nothing found (terminal).
        CheckConstraint(
            "image_status IS NULL OR image_status IN "
            "('resolved','placeholder','pending','user_uploaded')",
            name='image_status'),
        # Wave 2 GENERATION lifecycle (named CHECK; not diffed by autogenerate).
        # SEPARATE from image_status: a photo cutout stays image_status='user_uploaded'
        # while generation_status tracks the clean product-card image built FROM it.
        # NULL = not a generation target (e.g. Gmail candidates).
        CheckConstraint(
            "generation_status IS NULL OR generation_status IN "
            "('generating','ready','failed','pending_retry')",
            name='generation_status'),
        # Ingestion source (Wave 1). Mirrors clothing_items.source_type; confirm copies
        # it onto the closet row. Default 'gmail'; the photo pipeline stages 'photo'.
        CheckConstraint("source_type IN ('gmail','photo')", name='source_type'),
        # Content-key staging dedup (phase 3c): the same owned item appearing in
        # multiple emails collapses to ONE candidate via ON CONFLICT DO UPDATE.
        UniqueConstraint("user_id", "source_line_key",
                         name="ingest_candidates_user_id_source_line_key_key"),
        Index("idx_ingest_candidates_user_id", "user_id"),
        Index("idx_ingest_candidates_sync_id", "sync_id"),
        Index("idx_ingest_candidates_user_status", "user_id", "status"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    sync_id = Column(GUID(), nullable=True)

    # The representative (first-seen) Gmail message for this candidate. All
    # contributing messages are kept in source_message_ids below.
    message_id = Column(Text, nullable=True)

    # Content-based dedup key = hash(normalized_name + size + color + unit_price).
    # UNIQUE(user_id, source_line_key) is the staging dedup mechanism; 3d copies
    # this onto clothing_items.source_line_key at confirm time.
    source_line_key = Column(Text, nullable=True)

    # Every Gmail message that contributed this item (order + shipping + ...), so
    # collapsing emails never loses a source link.
    source_message_ids = Column(_text_array(), nullable=False, default=list)

    # Distinct source emails that contributed this candidate (>= 1).
    seen_count = Column(Integer, nullable=False, default=1)

    name = Column(Text, nullable=True)

    brand = Column(Text, nullable=True)

    category = Column(Text, nullable=True)

    color = Column(Text, nullable=True)

    size = Column(Text, nullable=True)

    quantity = Column(Integer, nullable=False, default=1)

    unit_price = Column(Numeric, nullable=True)

    currency = Column(Text, nullable=True)

    order_date = Column(Date, nullable=True)

    is_return = Column(Boolean, nullable=False, default=False)

    merchant = Column(Text, nullable=True)

    order_id = Column(Text, nullable=True)

    image_url = Column(Text, nullable=True)

    # Image lifecycle (Phase 4 streaming deck). resolved | placeholder | pending |
    # user_uploaded (CHECK above). Set 'resolved'/'pending' at extraction (fast tiers),
    # flipped to 'resolved'/'placeholder' by the background image-fill worker.
    image_status = Column(Text, nullable=True)

    # Wave 2 generation: the VERIFIED clean product-card image generated from the
    # cutout. image_url stays the raw cutout (verify reference + last-resort); this is
    # the card the deck shows once generation passes the fidelity gate. NULL until then.
    generated_image_url = Column(Text, nullable=True)

    # Wave 2 generation lifecycle (CHECK above), independent of image_status:
    # generating | ready | failed | pending_retry. NULL = not a generation target.
    generation_status = Column(Text, nullable=True)

    confidence_overall = Column(Numeric, nullable=True)

    confidence_json = Column(_jsonb(), nullable=True)

    status = Column(Text, nullable=False, default="pending")

    # Ingestion source: 'gmail' | 'photo'. Default 'gmail' so the existing extraction
    # pipeline needs no change; the photo pipeline sets 'photo' at stage time.
    source_type = Column(Text, nullable=False, default="gmail")

    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)


class ProcessedUpload(Base):
    """Per-(user, image) idempotency ledger for the photo-ingest pipeline (Wave 1).

    The Gmail analogue is processed_messages (keyed on the Gmail message id). Photos
    have no message id, so this table keys on the sha256 of the uploaded bytes: a
    re-upload of the EXACT same file is short-circuited (reprocess nothing). ``phash``
    holds a perceptual hash so a NEAR-duplicate shot (re-compressed / trivially
    cropped) can also be skipped without a second full detect+crop+stage pass.

    Per-user RLS (auth.uid() = user_id), applied in migration 0014, matches the other
    ingestion tables. user_id is server-pinned from the JWT, never the request body.
    """

    __tablename__ = "processed_uploads"

    __table_args__ = (
        UniqueConstraint("user_id", "image_sha256",
                         name="processed_uploads_user_id_image_sha256_key"),
        CheckConstraint(
            "status IN ('processed','held_multi_person','error')", name="status"),
        Index("idx_processed_uploads_user_id", "user_id"),
        # Near-dup lookups scan a user's recent phashes — index the (user, phash) pair.
        Index("idx_processed_uploads_user_phash", "user_id", "phash"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # The photo-ingest run (ingest_runs.sync_id) this upload was processed under.
    sync_id = Column(GUID(), nullable=True)

    # sha256 hex of the ORIGINAL uploaded bytes — the exact-dup idempotency key.
    image_sha256 = Column(Text, nullable=False)

    # 16-hex-char 64-bit perceptual dHash for near-duplicate detection (NULL if a held
    # upload never got far enough to hash the decoded image).
    phash = Column(Text, nullable=True)

    # processed | held_multi_person (>1 person detected; skipped, not guessed) | error.
    status = Column(Text, nullable=False, default="processed")

    # How many garment candidates this upload staged (0 for held/error).
    item_count = Column(Integer, nullable=False, default=0)

    processed_at = Column(_tstz(), default=datetime.utcnow, nullable=False)


class PhotoDetectSession(Base):
    """Transient detect -> select -> commit handoff for photo ingest (Wave 1.5).

    Wave 1.5 splits the photo pipeline into two requests: POST /photo/ingest/detect
    runs Gemini detection and returns the regions for the user to pick from; POST
    /photo/ingest/commit re-receives the SAME files and stages only the selected
    regions. The source photo is NEVER persisted to storage (unchanged from Wave 1),
    so this row is the only server-side state between the two steps: the detection
    output (boxes + optional model masks + attributes, as JSON) keyed by the photo's
    sha256, which is how commit binds a re-uploaded file back to its session.

    Transient by design: expires_at (config PHOTO_SESSION_TTL_HOURS) bounds the row's
    life; detect opportunistically sweeps the caller's expired 'pending' rows; commit
    flips status to 'committed'. No image bytes live here — hashes, dimensions, boxes,
    and mask PNGs (model output scoped to a box) only.

    Per-user RLS (auth.uid() = user_id) applied in migration 0015. user_id is
    server-pinned from the JWT, never the request body; every query filters on it.
    """

    __tablename__ = "photo_detect_sessions"

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','committed','expired')", name="status"),
        Index("idx_photo_detect_sessions_user_id", "user_id"),
        # Commit + upsert both look sessions up by (user, photo hash).
        Index("idx_photo_detect_sessions_user_sha", "user_id", "image_sha256"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # sha256 hex of the ORIGINAL uploaded bytes — how commit re-binds the re-received
    # file to this session (the photo itself is never stored).
    image_sha256 = Column(Text, nullable=False)

    # Perceptual dHash, carried through to the processed_uploads row at commit.
    phash = Column(Text, nullable=True)

    # Sanitized-image pixel dimensions, so the client can map 0..1000 boxes to pixels.
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)

    # Distinct people the detector saw. Stored, surfaced to the client — Wave 1.5 no
    # longer holds multi-person photos (the user disambiguates by selecting regions).
    person_count = Column(Integer, nullable=False, default=0)

    # [{region_id, box_2d[4], mask|null, name, category, color, pattern, material,
    #   fit, brand, confidence_overall, confidence{per-field}}]. Masks live ONLY here
    # (never in API responses); commit reads them back for the cutout.
    regions = Column(_jsonb(), nullable=False, default=list)

    # pending | committed | expired (CHECK above).
    status = Column(Text, nullable=False, default="pending")

    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)

    # Hard TTL: commit refuses (410) past this; detect sweeps expired pending rows.
    expires_at = Column(_tstz(), nullable=False)


class PhotoUsage(Base):
    """Per-user per-MONTH photo-quota rollup — the free-tier ledger (30 photos/month)
    that SCRUM-44 enforcement will READ. Incremented via atomic upsert so it stays
    correct across the web + worker processes. Counts only; never image content.

    ``period_start`` is the FIRST day of the usage month (UTC) — the monthly analogue
    of chat_usage's per-DAY ``period_start`` (app/models/stylist.py ChatUsage). Every
    quota-consuming photo action bumps ``photos_used``; ``regenerations`` breaks out the
    Regenerate subset for reporting. No enforcement lives here yet — this table is the
    counter SCRUM-44 will check.

    Per-user RLS (auth.uid() = user_id, all four verbs) applied by migration 0028; RLS
    is not expressible in the ORM. user_id is server-pinned from the JWT, never a body.
    """

    __tablename__ = "photo_usage"

    __table_args__ = (
        UniqueConstraint("user_id", "period_start",
                         name="photo_usage_user_id_period_start_key"),
        Index("idx_photo_usage_user_id", "user_id"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # First day of the usage month (UTC).
    period_start = Column(Date, nullable=False)
    # Every quota-consuming photo action this month (ingest commit + regenerate).
    photos_used = Column(Integer, nullable=False, default=0)
    # Regenerate subset of photos_used (reporting only).
    regenerations = Column(Integer, nullable=False, default=0)
    updated_at = Column(_tstz(), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class IngestRun(Base):
    """Per-sync status/progress. sync_id is the run identifier the UI polls."""

    __tablename__ = "ingest_runs"

    __table_args__ = (
        CheckConstraint("status IN ('running','completed','error')", name="status"),
        # Which ingestion source this run belongs to: 'gmail' | 'photo' (Wave 1).
        CheckConstraint("source_type IN ('gmail','photo')", name="source_type"),
        # What kicked this run (Wave C / Fix 1): 'onboarding' (the connect auto-scan) |
        # 'manual' (the explicit "Scan my inbox" CTA). NULL for pre-0031 runs. Named CHECK
        # (not diffed by autogenerate); owned by migration 0031.
        CheckConstraint(
            "\"trigger\" IS NULL OR \"trigger\" IN ('onboarding','manual')", name="trigger"
        ),
        Index("idx_ingest_runs_user_id", "user_id"),
    )

    sync_id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # The durable job that owns this run (P3.8 / R1). Nullable + ON DELETE SET
    # NULL: NULL for every pre-0026 run and for runs dispatched via the legacy
    # BackgroundTasks path (flags OFF). When set, the reclaim sweep can flip a
    # stuck 'running' status to 'error' after its owning job dies — so /status
    # stops lying after a worker crash. Owned by migration 0026.
    job_id = Column(GUID(), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)

    status = Column(Text, nullable=False, default="running")

    # Ingestion source for this run: 'gmail' (default) | 'photo'. The photo route sets
    # 'photo' so /status and per-source reporting can disambiguate runs.
    source_type = Column(Text, nullable=False, default="gmail")

    fetched_count = Column(Integer, nullable=False, default=0)

    filtered_count = Column(Integer, nullable=False, default=0)

    extracted_count = Column(Integer, nullable=False, default=0)

    # Gmail resultSizeEstimate captured at list time; NULL until the list phase completes.
    total_estimate = Column(Integer, nullable=True)

    # --- Per-sync cost tracking (Feature B) -------------------------------------
    # REAL recorded usage attributed to this sync, broken out by tier. Counts +
    # dollars only — never any email content. Dollars are computed from the counts ×
    # the editable config rates (app/gmail_closet/usage.py). Server defaults (0) are
    # owned by migration 0012.
    gemini_input_tokens = Column(BigInteger, nullable=False, default=0)   # extraction
    gemini_output_tokens = Column(BigInteger, nullable=False, default=0)  # extraction
    verify_input_tokens = Column(BigInteger, nullable=False, default=0)   # vision-verify
    verify_output_tokens = Column(BigInteger, nullable=False, default=0)  # vision-verify
    serper_credits = Column(Integer, nullable=False, default=0)           # shopping search
    extract_cost_usd = Column(Numeric, nullable=False, default=0)
    verify_cost_usd = Column(Numeric, nullable=False, default=0)
    search_cost_usd = Column(Numeric, nullable=False, default=0)
    cost_usd = Column(Numeric, nullable=False, default=0)                 # = extract+verify+search

    # --- Wave 2 product-image generation progress (photo runs) ------------------
    # Per-run counters so GET /ingest/status reports generation-in-flight (drives the
    # add-photo "Preparing N items -> Review ready" pill). 0 for Gmail runs. Server
    # defaults (0) owned by migration 0016.
    generation_total = Column(Integer, nullable=False, default=0)   # candidates to generate
    generation_ready = Column(Integer, nullable=False, default=0)   # verified + stored
    generation_failed = Column(Integer, nullable=False, default=0)  # held pending_retry

    started_at = Column(_tstz(), default=datetime.utcnow, nullable=False)

    finished_at = Column(_tstz(), nullable=True)

    # --- Wave C / Fix 1: onboarding background scan + Home review banner ---------
    # trigger: 'onboarding' | 'manual' (CHECK above). NULL for pre-0031 runs.
    trigger = Column(Text, nullable=True)
    # Show-once state for the Home "review N items ready" banner. GET /pending-review
    # surfaces a completed run only while BOTH are NULL; opening the banner stamps
    # review_surfaced_at, an explicit dismiss stamps review_dismissed_at — either retires it.
    review_surfaced_at = Column(_tstz(), nullable=True)
    review_dismissed_at = Column(_tstz(), nullable=True)
