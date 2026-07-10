"""Closet / wardrobe-item models (clothing_items, item_images).

Split out of the former monolithic app/models.py (P3.2, ARCHITECTURE_AUDIT R4).
Re-exported from app.models for backward compatibility -- see
app/models/__init__.py.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column, String, DateTime, Date, Boolean, ForeignKey, Text, Integer, BigInteger,
    Numeric, UniqueConstraint, CheckConstraint, Index, text,
)
from sqlalchemy.orm import relationship

from app.db import Base, GUID
from app.models._shared import _jsonb, _text_array, _tstz


def display_image_url(item) -> Optional[str]:
    """The clothing item's image_url that is SAFE TO DISPLAY, or None (placeholder).

    THE single display gate every surface must go through — closet list/detail, the
    stylist retrieval serialization, and the Today's-Look / lookbook collages.
    FAIL-CLOSED, and since Photo-seam Phase 5 GENERATED-CARD-ONLY for the photo/manual
    sources:

      * source_type 'photo'/'manual': the image shows ONLY when generation_status=
        'ready' — image_url then IS the verified, invariant-compliant generated card
        (the writers replace the crop with the card in the same transaction; the pair
        verify hard-fails person_present/extra-items/background/framing). Any other
        state (pending_retry, failed, generating, legacy person_free RAW CROPS) →
        None. A raw source crop is a GENERATION REFERENCE, never a display source.

      * source_type 'gmail' (default): the resolved, verified retailer/email product
        image is the card; it shows only on an AFFIRMATIVE person_free verdict (or a
        ready generated card from the on-model routing). 'unknown' (no verify ever
        ran) and 'person_present' stay masked — "unchecked" never reads as "clean".
    """
    if (getattr(item, "source_type", None) or "gmail") in ("photo", "manual"):
        if getattr(item, "generation_status", None) == "ready":
            return item.image_url
        return None
    gen_status = getattr(item, "generation_status", None)
    if gen_status == "ready":
        return item.image_url
    if gen_status in ("pending_retry", "generating", "failed"):
        # Photo-seam Phase 6: a gmail item put INTO the generation pipeline (e.g. the
        # backfill sweep found its resolved image non-compliant and demoted it for
        # regeneration) is masked until a compliant card lands — person_free alone no
        # longer overrides an explicit "this image needs replacing" verdict.
        return None
    if getattr(item, "person_status", None) == "person_free":
        return item.image_url
    return None


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
        # receipt pipeline), 'photo' (a garment detected from a user-uploaded photo),
        # or 'manual' (Photo-seam Phase 4, migration 0036 — a typed manual add routed
        # through the candidate -> generation -> confirm chokepoint). Named CHECK (not
        # diffed by autogenerate); server default 'gmail' owned by migration 0014.
        CheckConstraint("source_type IN ('gmail','photo','manual')", name='source_type'),
        # Fail-closed person tri-state (ready-first Phase 1, migration 0035). Named CHECK
        # (not diffed by autogenerate); mirrors ingest_candidates.person_status.
        CheckConstraint(
            "person_status IN ('unknown','person_present','person_free')",
            name='person_status'),
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

    # NOT NULL (migration 0030): every write funnels through the canonicalization
    # chokepoint (app.services.closet_canonicalize) which guarantees a category, so this
    # is the hard backstop against a null-category leak. Value space = the CHECK below.
    category = Column(Text, nullable=False)

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

    # Count of FAILED generate->verify attempts (cost cut #2, migration 0034). After
    # GENERATION_MAX_ATTEMPTS the item goes terminal ('failed') and self-heal never
    # re-selects it; transient misses (download error / budget) don't increment it.
    generation_attempts = Column(Integer, nullable=False, default=0, server_default="0")

    # Ingestion source: 'gmail' (receipts) | 'photo' (user-uploaded photo). NOT NULL;
    # server default 'gmail' (migration 0014) backfills legacy rows. Confirm copies the
    # candidate's source_type forward so the closet records how each item arrived.
    source_type = Column(Text, nullable=False, default="gmail")

    # G6: carried from the confirmed candidate — this item's photo cutout is ON-MODEL (has a
    # person). image_url keeps the crop ONLY as the generation/self-heal reference; the read
    # layer NEVER returns it until a verified person-free card lands (generation_status=
    # 'ready'). false for Gmail + flat-lay photo items. Owned by migration 0032. Kept for
    # the photo detector/self-heal; person_status below is the fail-closed DISPLAY key.
    on_model = Column(Boolean, nullable=False, default=False)

    # Fail-closed person tri-state (ready-first Phase 1, migration 0035). 'unknown'
    # (default — no detector ever ran; all legacy Gmail rows) | 'person_present' |
    # 'person_free'. display_image_url shows a raw image ONLY on 'person_free' (or a
    # verified 'ready' generated card). Carried from the candidate at confirm.
    person_status = Column(Text, nullable=False, default="unknown", server_default="unknown")

    # Photo-seam Phase 6 (migration 0037): when this item's image was validated against
    # the verify-v2 invariant gates. NULL = a backfill-sweep target; carried from the
    # candidate at confirm, stamped by the regeneration/self-heal writers.
    invariant_checked_at = Column(_tstz(), nullable=True)

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
