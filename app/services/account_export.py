"""GDPR data export — one human-readable JSON of everything Tailor holds about a
user, built for ``GET /account/export``.

Deliberately SYNC: a user's footprint is small (a closet of tens–hundreds of items
plus a style profile and a handful of outfits — well under a megabyte of JSON), so
there is no need for an async job + email-a-link dance. We assemble and return it
in-request as a downloadable attachment.

What it INCLUDES: the profile, the distilled style facts / learned preferences /
narrative, every closet item with its human-readable attributes, saved outfits,
and an activity (events) summary.

What it EXCLUDES on purpose:
  * All token material — Gmail/Calendar access & refresh tokens, scopes (encrypted
    at rest; never exported). Connections appear only as booleans + connected-at.
  * ``hashed_password`` and any auth secret.
  * Internal plumbing: embeddings, image blob hashes / cache keys, job rows, raw
    generation/cutout lifecycle columns, and internal ids beyond each item's own id
    (kept so exported outfits can reference their items).
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import (
    CalendarAccount,
    ClothingItem,
    GoogleAccount,
    SavedOutfit,
    StyleEvent,
    StylePreference,
    StyleProfile,
    User,
)

# Human-facing closet attributes to export (never the internal generation/cutout/
# image-cache plumbing or provenance blobs). ``id`` is included so saved outfits'
# item_ids resolve within the export.
_CLOTHING_FIELDS = (
    "id", "name", "category", "sub_category", "color_primary", "color_secondary",
    "color_primary_hex", "pattern", "material", "fit_silhouette", "fit_rise",
    "brand", "size", "formality", "warmth", "seasons", "occasions", "length",
    "neckline", "sleeve_length", "heel_height", "condition", "is_favorite",
    "wear_count", "last_worn_at", "acquired_date", "merchant", "order_date",
    "unit_price", "currency", "quantity", "is_return", "image_url", "source_type",
    "created_at",
)


def _json_safe(value: Any) -> Any:
    """Coerce a DB value into something ``json.dumps`` handles, human-readably."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return value


def build_account_export(db: Session, user: User) -> Dict[str, Any]:
    """Assemble the full export document for ``user``."""
    google = db.query(GoogleAccount).filter(GoogleAccount.user_id == user.id).first()
    calendar = db.query(CalendarAccount).filter(CalendarAccount.user_id == user.id).first()

    profile: StyleProfile | None = (
        db.query(StyleProfile).filter(StyleProfile.user_id == user.id).first()
    )
    preferences: List[StylePreference] = (
        db.query(StylePreference)
        .filter(StylePreference.user_id == user.id)
        .order_by(StylePreference.dimension)
        .all()
    )
    items: List[ClothingItem] = (
        db.query(ClothingItem)
        .filter(ClothingItem.user_id == user.id)
        .order_by(ClothingItem.created_at)
        .all()
    )
    outfits: List[SavedOutfit] = (
        db.query(SavedOutfit)
        .filter(SavedOutfit.user_id == user.id)
        .order_by(SavedOutfit.created_at)
        .all()
    )
    events: List[StyleEvent] = (
        db.query(StyleEvent).filter(StyleEvent.user_id == user.id).all()
    )

    return {
        "export_format_version": 1,
        "account": {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "full_name": user.full_name,
            "created_at": _json_safe(user.created_at),
            "connections": {
                # Booleans only — no token material is ever exported.
                "gmail_connected": bool(google and google.refresh_token),
                "gmail_connected_at": _json_safe(google.created_at) if google else None,
                "calendar_connected": bool(calendar and calendar.refresh_token),
                "calendar_connected_at": _json_safe(calendar.created_at) if calendar else None,
            },
        },
        "style_profile": (
            {
                "summary": profile.summary,
                "facts": _json_safe(profile.facts),
                "narrative": _json_safe(profile.narrative_blob),
                "distilled_at": _json_safe(profile.distilled_at),
                "updated_at": _json_safe(profile.updated_at),
            }
            if profile
            else None
        ),
        "learned_preferences": [
            {
                "dimension": p.dimension,
                "value": _json_safe(p.value),
                "polarity": p.polarity,
                "confidence": _json_safe(p.confidence),
                "source": p.source,
                "evidence": p.evidence,
                "evidence_count": p.evidence_count,
                "updated_at": _json_safe(p.updated_at),
            }
            for p in preferences
        ],
        "closet_items": [
            {f: _json_safe(getattr(item, f)) for f in _CLOTHING_FIELDS}
            for item in items
        ],
        "saved_outfits": [
            {
                "title": o.title,
                "item_ids": _json_safe(o.item_ids),
                "rationale": o.rationale,
                "occasion": o.occasion,
                "source": o.source,
                "status": o.status,
                "worn_at": _json_safe(o.worn_at),
                "is_liked": o.is_liked,
                "created_at": _json_safe(o.created_at),
            }
            for o in outfits
        ],
        "activity_summary": {
            "total_events": len(events),
            "events_by_type": dict(Counter(e.event_type for e in events)),
        },
        "counts": {
            "closet_items": len(items),
            "saved_outfits": len(outfits),
            "learned_preferences": len(preferences),
        },
    }
