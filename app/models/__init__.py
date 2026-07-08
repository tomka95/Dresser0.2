"""ORM models package (P3.2, ARCHITECTURE_AUDIT R4).

Split from the former monolithic app/models.py into one module per bounded
context, grouped by domain rather than by table-creation order:

  user         -- public.users (Supabase Auth profile table)
  closet       -- clothing_items, item_images
  ingestion    -- google_accounts, processed_messages, ingest_candidates,
                  processed_uploads, photo_detect_sessions, ingest_runs
  image        -- image_blobs, product_image_cache (shared image system)
  stylist      -- item_embeddings, style_events/profiles/preferences,
                  preference_signals, + the chat vertical (conversations,
                  chat_messages, saved_outfits, chat_usage, chat_rate_windows)
  ranking      -- products, product_embeddings, user_wardrobe_gap
  monetization -- product_clicks, affiliate_conversions
  ops          -- weather_cache, waitlist

Every class name importable from the old `app.models` module stays importable
from `app.models` unchanged (`from app.models import ClothingItem` etc.) via
the re-exports below -- no caller anywhere in the codebase needs to change.
SQLAlchemy metadata is unaffected: every model still subclasses the SAME
`Base` (app.db.Base), so `Base.metadata` ends up populated identically
regardless of which file declares which class. `alembic check` proves this
(see ARCHITECTURE_AUDIT.md P3.2).

Importing this package (or any submodule) is what registers every model
against Base.metadata -- alembic/env.py's `import app.models` relies on this
exactly as it did when models.py was a single file.
"""

# Re-export the shared base/UUID type for parity with the pre-split module,
# where `from .db import Base, GUID` made these attributes of `app.models` too.
from app.db import Base, GUID

from app.models.user import User
from app.models.closet import ClothingItem, ItemImage
from app.models.ingestion import (
    CalendarAccount,
    GoogleAccount,
    IngestCandidate,
    IngestRun,
    PhotoDetectSession,
    PhotoUsage,
    ProcessedMessage,
    ProcessedUpload,
)
from app.models.image import ImageBlob, ProductImageCache
from app.models.stylist import (
    ChatMessage,
    ChatRateWindow,
    ChatUsage,
    Conversation,
    ItemEmbedding,
    PreferenceSignal,
    SavedOutfit,
    StyleEvent,
    StylePreference,
    StyleProfile,
    TodaysLookCache,
)
from app.models.ranking import Product, ProductEmbedding, UserWardrobeGap
from app.models.monetization import AffiliateConversion, ProductClick
from app.models.ops import Waitlist, WeatherCache
from app.models.jobs import Job

__all__ = [
    "Base",
    "GUID",
    "User",
    "ClothingItem",
    "ItemImage",
    "CalendarAccount",
    "GoogleAccount",
    "ProcessedMessage",
    "IngestCandidate",
    "ProcessedUpload",
    "PhotoDetectSession",
    "PhotoUsage",
    "IngestRun",
    "ImageBlob",
    "ProductImageCache",
    "ItemEmbedding",
    "Product",
    "ProductEmbedding",
    "ProductClick",
    "AffiliateConversion",
    "UserWardrobeGap",
    "StyleEvent",
    "StyleProfile",
    "StylePreference",
    "PreferenceSignal",
    "Conversation",
    "ChatMessage",
    "SavedOutfit",
    "ChatUsage",
    "ChatRateWindow",
    "TodaysLookCache",
    "WeatherCache",
    "Waitlist",
    "Job",
]
