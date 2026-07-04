import uuid

from datetime import datetime

from sqlalchemy import (
    Column, String, DateTime, Date, Boolean, ForeignKey, Text, Integer, BigInteger,
    SmallInteger, Float, Double, Numeric, REAL, UniqueConstraint, CheckConstraint,
    Table, Index, JSON, text,
)
from sqlalchemy.dialects.postgresql import JSONB, ARRAY as PG_ARRAY, UUID as PG_UUID
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector


# Timestamp helper: the live DB uses `timestamp with time zone` for nearly every
# timestamp column. Use this so ORM metadata matches and autogenerate stays clean.
def _tstz(**kw):
    return DateTime(timezone=True)

from .db import Base, GUID


# --- Cross-dialect column helpers -------------------------------------------
# Production runs on PostgreSQL (Supabase); the optional LOCAL_DB=sqlite dev mode
# needs the same models to map cleanly. These mirror the intent of the GUID type:
# the real Postgres column type, with a portable SQLite fallback.
#
# Note: server-side defaults (e.g. ''{}''::text[], gen_random_uuid()) live in the
# Alembic baseline migration, which owns the schema. The Python-side defaults below
# keep ORM inserts working on both dialects without emitting Postgres-only DDL.
def _jsonb():
    return JSONB().with_variant(JSON(), "sqlite")


def _text_array():
    return PG_ARRAY(Text()).with_variant(JSON(), "sqlite")


def _uuid_array():
    # Postgres uuid[]; JSON fallback under the SQLite dev/test create_all() path.
    return PG_ARRAY(PG_UUID(as_uuid=True)).with_variant(JSON(), "sqlite")


# pgvector column (Postgres `vector(dim)`), with a portable SQLite fallback so the
# LOCAL_DB=sqlite dev/test create_all() path doesn't choke on the vector type (tests
# never read/write embeddings). dim is fixed at DDL time; see EMBEDDING_DIM in config.
def _vector(dim):
    return Vector(dim).with_variant(Text(), "sqlite")




class User(Base):

    __tablename__ = "users"

    # Live uses UNIQUE constraints (users_email_key / users_google_sub_key), not
    # the auto-named ix_* indexes that Column(unique=True, index=True) would create.
    __table_args__ = (
        UniqueConstraint("email", name="users_email_key"),
        UniqueConstraint("google_sub", name="users_google_sub_key"),
    )


    # Supabase Auth transition: public.users is a PROFILE table whose id equals the
    # corresponding auth.users id. The FK users.id -> auth.users(id) is added by
    # Alembic revision 0002 and is owned exclusively by that migration -- it is NOT
    # declared here, because auth.users is a Supabase/Postgres-only table that must
    # not be a mapped model (modeling it would break create_all() under the SQLite
    # dev/test mode). alembic/env.py::_include_object excludes this FK from
    # autogenerate so the ORM<->live parity stays clean. The uuid4 default remains
    # for the legacy custom-JWT signup path; Supabase-provisioned profiles set id
    # explicitly to the token's `sub`.
    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    # Live: email is `character varying`; the rest are `text`.
    email = Column(String, nullable=False)

    hashed_password = Column(Text, nullable=False)

    display_name = Column(Text, nullable=True)

    google_sub = Column(Text, nullable=True)

    full_name = Column(Text, nullable=True)

    avatar_url = Column(Text, nullable=True)

    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)

    gmail_sync_completed_at = Column(DateTime(timezone=True), nullable=True)


    clothing_items = relationship("ClothingItem", back_populates="user", cascade="all, delete-orphan")

    google_account = relationship("GoogleAccount", back_populates="user", uselist=False)




class ClothingItem(Base):

    __tablename__ = "clothing_items"

    __table_args__ = (
        Index('idx_clothing_items_user_id', 'user_id'),
        # created_at is DESC in the live DB (recent-first queries). Expressed via
        # text() so ORM metadata matches reflection and autogenerate stays clean.
        Index('idx_clothing_items_user_id_created_at', 'user_id', text('created_at DESC')),
        # GIN indexes present live. postgresql_using='gin' is honored on Postgres
        # and ignored on SQLite (create_all emits a plain index there). The dead
        # tags/colors/style_tags GINs were dropped with their columns in 0018.
        Index('clothing_items_analysis_raw_gin', 'analysis_raw', postgresql_using='gin'),
        Index('idx_clothing_items_attributes_json_gin', 'attributes_json', postgresql_using='gin'),
        # --- Ingestion (phase 3a) -------------------------------------------
        # THE single dedup key: re-confirming the same receipt line never inserts
        # twice. Replaces the old pipeline's two disagreeing keys. Legacy rows have
        # source_line_key NULL (distinct under Postgres), so they don't collide.
        UniqueConstraint('user_id', 'source_line_key',
                         name='clothing_items_user_id_source_line_key_key'),
        # 3-char ISO-4217 currency guard. length() (not char_length()) so the
        # constraint is also valid under the SQLite dev/test dialect.
        CheckConstraint('currency IS NULL OR length(currency) = 3',
                        name='currency'),
        # image_status lifecycle enum (named CHECK; not diffed by autogenerate).
        # NULL allowed for rows created before the column / by paths that don't set it.
        CheckConstraint(
            "image_status IS NULL OR image_status IN "
            "('resolved','placeholder','pending','user_uploaded')",
            name='image_status'),
        # Wave 2 generation lifecycle carried from the confirmed candidate (named CHECK;
        # not diffed by autogenerate). Same vocabulary as ingest_candidates. NULL = not a
        # generation item (Gmail / manual). 'pending_retry' rows are what a later
        # generation self-heal sweep re-attempts.
        CheckConstraint(
            "generation_status IS NULL OR generation_status IN "
            "('generating','ready','failed','pending_retry')",
            name='generation_status'),
        # Ingestion source provenance (Wave 1 photo ingest). 'gmail' (default, the
        # receipt pipeline) or 'photo' (a garment detected from a user-uploaded
        # photo). Named CHECK (not diffed by autogenerate); server default 'gmail'
        # owned by migration 0014 backfills every legacy row.
        CheckConstraint("source_type IN ('gmail','photo')", name='source_type'),
        # --- AI Stylist universal garment schema (Wave S0, migration 0018) --------
        # Named CHECKs (not diffed by autogenerate). category is a SUPERSET: the
        # canonical 12 + the legacy aliases ('shoes','accessories','other') that still
        # live in the data / are emitted by the current 7-enum path (Branch B
        # normalizes them; a later migration tightens to the 12). subcategory reuses
        # the existing sub_category column (72 Fashionpedia-derived values).
        CheckConstraint(
            "category IS NULL OR category IN ("
            "'top','bottom','dress','outerwear','footwear','bag','accessory',"
            "'activewear','swim','lounge_underwear','suiting','jewelry',"
            "'shoes','accessories','other')",
            name='category'),
        CheckConstraint(
            "sub_category IS NULL OR sub_category IN ("
            "'t_shirt','tank_top','blouse','shirt','polo','sweater','hoodie','cardigan',"
            "'jeans','trousers','chinos','shorts','sweatpants','skirt_mini','skirt_midi','leggings',"
            "'mini_dress','midi_dress','maxi_dress','gown','shirt_dress',"
            "'jacket','denim_jacket','leather_jacket','blazer','coat','trench_coat','parka','vest',"
            "'sneaker','boot','ankle_boot','heel','loafer','oxford','sandal','flat',"
            "'tote_bag','crossbody_bag','shoulder_bag','backpack','clutch','belt_bag',"
            "'belt','hat','cap','beanie','scarf','gloves','sunglasses','tie','watch',"
            "'sports_bra','athletic_shorts','joggers','track_jacket',"
            "'bikini','one_piece_swimsuit','swim_trunks',"
            "'bra','underwear','boxers','pajamas','robe','lingerie',"
            "'suit','suit_jacket','suit_trousers',"
            "'necklace','bracelet','earrings','ring')",
            name='sub_category'),
        CheckConstraint('formality IS NULL OR (formality >= 1 AND formality <= 5)',
                        name='formality'),
        CheckConstraint('warmth IS NULL OR (warmth >= 1 AND warmth <= 3)',
                        name='warmth'),
        CheckConstraint(
            "condition IS NULL OR condition IN "
            "('new','like_new','good','fair','worn','damaged')",
            name='condition'),
    )


    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)


    # Live: all of these are `text`.
    name = Column(Text, nullable=False)

    category = Column(Text, nullable=True)

    sub_category = Column(Text, nullable=True)

    color_primary = Column(Text, nullable=True)

    color_secondary = Column(Text, nullable=True)

    brand = Column(Text, nullable=True)

    size = Column(Text, nullable=True)

    image_url = Column(Text, nullable=True)

    # --- Ingestion provenance + structured receipt fields (phase 3a) ---------
    # Populated by the 3b Gmail->closet pipeline; NULL for items created via the
    # photo pipeline or manual entry.
    source_message_id = Column(Text, nullable=True)

    source_google_account_id = Column(
        BigInteger,
        ForeignKey("google_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )

    source_line_key = Column(Text, nullable=True)

    order_id = Column(Text, nullable=True)

    order_date = Column(Date, nullable=True)

    unit_price = Column(Numeric, nullable=True)

    currency = Column(Text, nullable=True)

    quantity = Column(Integer, nullable=False, default=1)

    is_return = Column(Boolean, nullable=False, default=False)

    ingest_confidence = Column(Numeric, nullable=True)

    # Merchant the item was purchased from. Persisted at confirm (Wave 2a) from the
    # contributing ingest_candidate so the closet no longer joins candidates at
    # display time. NULL for photo-pipeline / manual items.
    merchant = Column(Text, nullable=True)

    # Image lifecycle (Wave 2a, additive — consumed by self-healing in a later wave).
    # image_status: resolved | placeholder | pending | user_uploaded (CHECK above).
    image_status = Column(Text, nullable=True)
    # The product_image_cache.cache_key this item maps to (shared-cache linkage).
    image_cache_key = Column(Text, nullable=True)

    # Wave 2 generation lifecycle, carried from the confirmed candidate. 'ready' =
    # image_url above IS the verified generated product card; 'pending_retry' = image_url
    # is the raw crop fallback and a later generation self-heal should re-attempt;
    # 'failed' = crop, terminal; NULL = not a generation item. Mirrors
    # ingest_candidates.generation_status (CHECK above).
    generation_status = Column(Text, nullable=True)

    # Ingestion source: 'gmail' (receipts) | 'photo' (user-uploaded photo). NOT NULL;
    # server default 'gmail' (migration 0014) backfills legacy rows. Confirm copies the
    # candidate's source_type forward so the closet records how each item arrived.
    source_type = Column(Text, nullable=False, default="gmail")

    analysis_raw = Column(_jsonb(), nullable=True)  # raw analysis/tags payload (jsonb in DB)

    # --- AI Stylist universal garment schema (Wave S0, migration 0018) -----------
    # Tier-1/2/4 attributes. All nullable / constant-default (no table rewrite). NOT
    # populated by any Branch-A code path — Branch B (enrichment) writes these; the
    # dead tags/colors/style_tags/tag_scores/color_scores columns were dropped in 0018.
    # sub_category (defined above) is the canonical subcategory carrier (72-value CHECK).
    #
    # Tier-1:
    color_primary_hex = Column(Text, nullable=True)
    pattern = Column(Text, nullable=True)
    material = Column(Text, nullable=True)
    fit_silhouette = Column(Text, nullable=True)
    fit_rise = Column(Text, nullable=True)
    formality = Column(Integer, nullable=True)   # 1..5 (CHECK above)
    warmth = Column(Integer, nullable=True)       # 1..3 (CHECK above)
    seasons = Column(_text_array(), nullable=True)
    occasions = Column(_text_array(), nullable=True)
    # Tier-2:
    length = Column(Text, nullable=True)
    neckline = Column(Text, nullable=True)
    sleeve_length = Column(Text, nullable=True)
    heel_height = Column(Text, nullable=True)
    # Tier-4 lifecycle:
    acquired_date = Column(Date, nullable=True)
    condition = Column(Text, nullable=True)       # CHECK above
    is_favorite = Column(Boolean, nullable=False, default=False)
    archived_at = Column(_tstz(), nullable=True)
    wear_count = Column(Integer, nullable=False, default=0)
    last_worn_at = Column(_tstz(), nullable=True)

    # Per-field provenance+confidence carrier (Branch B populates; {} until then).
    # Comment string is kept identical to the 0018 COMMENT ON COLUMN so `alembic
    # check` sees no drift.
    attributes_json = Column(
        _jsonb(), nullable=False, default=dict,
        comment=(
            'Per-field provenance+confidence carrier (Branch B populates; empty {} '
            'until then). Shape: {field: {value, confidence: 0..1, provenance: '
            'extracted|user_edited|inferred|default}}. user_edited is never '
            'overwritten by extraction/inference.'
        ),
    )

    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)

    updated_at = Column(_tstz(), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


    user = relationship("User", back_populates="clothing_items")

    images = relationship("ItemImage", back_populates="clothing_item", cascade="all, delete-orphan")




class ItemImage(Base):

    __tablename__ = "item_images"

    __table_args__ = (
        Index('idx_item_images_clothing_item_id', 'clothing_item_id'),
        # Partial index live: WHERE (is_primary = true). postgresql_where keeps the
        # ORM metadata identical to the DB.
        Index('idx_item_images_clothing_item_id_is_primary', 'clothing_item_id', 'is_primary',
              postgresql_where=text('is_primary = true')),
    )


    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    clothing_item_id = Column(GUID(), ForeignKey("clothing_items.id", ondelete="CASCADE"), nullable=False)

    image_url = Column(Text, nullable=False)

    type = Column(String, nullable=True)

    is_primary = Column(Boolean, default=False)


    # Live column is `timestamp WITHOUT time zone` (the one timestamp that is naive).
    created_at = Column(DateTime, default=datetime.utcnow)


    clothing_item = relationship("ClothingItem", back_populates="images")




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


class ImageBlob(Base):
    """Content-addressed dedup ledger for stored images (Wave 0 of the image system).

    Keyed by sha256 of the raw image bytes -> the ONE storage URL those bytes were
    uploaded to. Before the resolver uploads resolved image bytes it consults this
    table: identical bytes (across runs AND across users) reuse the existing URL
    instead of uploading a fresh uuid4 object every run, which is what was leaking
    orphaned blobs into the bucket.

    Deliberately NOT user-scoped: this is a GLOBAL dedup/cache table (no user_id,
    no per-user RLS — the migration locks it to the owner/service connection). It
    is the seed Wave 2a's shared image cache EXTENDS (additive columns only — ref
    counts / provenance / last_seen), never replaces.
    """

    __tablename__ = "image_blobs"

    # sha256 hex digest of the image bytes (64 chars). PK = the dedup key.
    content_sha256 = Column(Text, primary_key=True)

    # Public Supabase storage URL the bytes were uploaded to.
    image_url = Column(Text, nullable=False)

    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)


class ProductImageCache(Base):
    """Shared, cross-user product-image cache (Wave 2a): resolve-once-serve-many.

    Keyed by ``cache_key`` = stable hash of normalize(brand)+normalize(name)+
    canonical(color) (see app/gmail_closet/product_image_cache.py). A row maps a
    PRODUCT IDENTITY to one stored image URL (referencing an image_blobs blob), so
    the same product resolved for one user can be served to others — the
    proprietary-catalog byproduct.

    SAFETY: only rows with ``verified = true`` are ever served (the resolver read
    tier filters on it). Wave 2a writes ONLY ``verified = false`` staging rows; a
    later wave's vision-verify is the sole thing that flips ``verified`` true. So
    until then the read tier is a guaranteed no-op and no unverified / mis-associated
    image can leak to another user.

    NOT user-scoped on purpose — this is product catalog reference data: NO user_id,
    NO message/order data ever. RLS enabled with no policy (owner/service writes;
    anon/authenticated denied), mirroring image_blobs. Wave 2b EXTENDS this table.
    """

    __tablename__ = "product_image_cache"

    __table_args__ = (
        UniqueConstraint("cache_key", name="product_image_cache_cache_key_key"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    # Deterministic product-identity key (UNIQUE). See make_cache_key().
    cache_key = Column(Text, nullable=False)

    # Normalized identity components stored for debuggability / verification (2b).
    brand = Column(Text, nullable=True)
    name_norm = Column(Text, nullable=True)
    color_norm = Column(Text, nullable=True)

    # The served image URL + a link to the content-addressed blob it points at.
    image_url = Column(Text, nullable=False)
    content_sha256 = Column(
        Text,
        ForeignKey("image_blobs.content_sha256", ondelete="SET NULL"),
        nullable=True,
    )

    # Provenance of the staged image (which resolver tier / host produced it).
    source_tier = Column(Text, nullable=True)
    source_domain = Column(Text, nullable=True)

    # Gate: only verified rows are served. Set true ONLY by Wave 2b vision-verify.
    verified = Column(Boolean, nullable=False, default=False)
    verify_score = Column(Numeric, nullable=True)

    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)
    last_served_at = Column(_tstz(), nullable=True)
    serve_count = Column(Integer, nullable=False, default=0)




class IngestRun(Base):
    """Per-sync status/progress. sync_id is the run identifier the UI polls."""

    __tablename__ = "ingest_runs"

    __table_args__ = (
        CheckConstraint("status IN ('running','completed','error')", name="status"),
        # Which ingestion source this run belongs to: 'gmail' | 'photo' (Wave 1).
        CheckConstraint("source_type IN ('gmail','photo')", name="source_type"),
        Index("idx_ingest_runs_user_id", "user_id"),
    )

    sync_id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

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




# --- AI Stylist substrate (Wave S0, migration 0018) --------------------------
# Foundation tables the Stylist writes through in later branches (B: enrichment /
# item_embeddings; C: style_events; S1: style_profiles distillation). All carry
# UUID user_id -> users(id) and per-user RLS (auth.uid() = user_id), applied in the
# migration (RLS is not expressible in the ORM). The legacy user_preferences /
# user_preference_events (TEXT user_id, 0 rows, no live reader/writer) were dropped
# in 0018 and are SUPERSEDED by style_preferences / preference_signals.

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
        Index("idx_style_events_user_created_at", "user_id", text("created_at DESC")),
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
        Index("idx_preference_signals_user_created_at", "user_id", text("created_at DESC")),
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
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(Text, nullable=True)
    item_ids = Column(_uuid_array(), nullable=False)
    rationale = Column(Text, nullable=True)
    occasion = Column(Text, nullable=True)
    source = Column(Text, nullable=False, default="chat")
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


# --- Tables that exist live but were previously unmodeled in the ORM ---------
# Modeled here so the ORM and the Alembic baseline agree with the real database.
# These are not yet wired into any endpoint; they document the live schema and
# unblock future features (weather caching, waitlist).

class WeatherCache(Base):

    __tablename__ = "weather_cache"

    __table_args__ = (
        Index("idx_weather_cache_expires", "expires_at"),
        Index("idx_weather_cache_lookup", "provider", "lat", "lon", "timezone", "start_at", "end_at"),
        {"comment": "Cache for weather API responses to reduce external API calls"},
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    provider = Column(Text, nullable=False, comment="Weather provider name (e.g., open_meteo)")

    # Live: double precision (float8).
    lat = Column(Double, nullable=False)

    lon = Column(Double, nullable=False)

    timezone = Column(Text, nullable=False)

    start_at = Column(DateTime(timezone=True), nullable=False)

    end_at = Column(DateTime(timezone=True), nullable=False)

    payload = Column(_jsonb(), nullable=False, comment="Cached WeatherForecast JSON payload")

    fetched_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    expires_at = Column(DateTime(timezone=True), nullable=False,
                        comment="When this cache entry expires (UTC)")




class Waitlist(Base):

    __tablename__ = "waitlist"

    __table_args__ = (
        UniqueConstraint("email", name="waitlist_email_key"),
        Index("idx_waitlist_email", "email"),
        # created_at DESC live (recent-first). text() keeps metadata == reflection.
        Index("idx_waitlist_created_at", text("created_at DESC")),
        {"comment": "Stores email addresses of users who joined the waitlist"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    email = Column(String, nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

