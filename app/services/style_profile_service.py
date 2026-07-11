"""Read/write service for the "My Style Profile" screen (/profile/style).

Exposes the DB brain the app already builds — style_profiles (facts + distilled
narrative) and style_preferences (learned per-dimension tastes) — to the user,
and lets the user correct it. It is the FIRST user-facing write path into the
preference substrate, so it carries two guarantees:

  * SACRED WRITES — any user edit to a learned preference stamps
    ``value.user_edited = True`` (mirrors the closet attributes_json
    provenance='user_edited' rule). Distillation is taught to freeze such rows
    (see app.services.stylist.distill._is_user_locked), so a later re-distill
    NEVER overwrites what the user asserted.

  * TOMBSTONES — deleting a learned preference does NOT drop the row. It keeps
    the (user_id, dimension) row, flips ``active=False`` and stamps
    ``value.user_edited = value.deleted = True``. Because the UNIQUE(user_id,
    dimension) slot stays occupied by a frozen row, the nightly recompute can
    never re-derive that dimension from old preference_signals — the forget is
    permanent, not a one-run suppression.

Reads mirror app.services.stylist.profile.assemble_profile (active prefs, by
confidence). Never returns raw preference_signals or un-whitelisted facts keys.
The caller runs everything inside an RLS-scoped session and owns the commit.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import StylePreference, StyleProfile
from app.services.onboarding_service import (
    OnboardingValidationError,
    _sanitize_json,
    sanitize_facts,
)
from app.services.stylist.distill import DIMENSIONS as _TYPED_DIMENSIONS
from app.services.stylist.profile import _narrative_text

# Facts keys the screen renders and the user may edit. Everything else in
# style_profiles.facts (avoid-lists, location, budget, server bookkeeping) is
# NEVER exposed or accepted here. Body/measurement fields are deliberately absent
# — the product has never asked for them and must not start now.
EXPOSED_FACT_KEYS = frozenset({"sizes", "fits", "fit_preference", "department", "occasions"})

# Sidecar list inside facts recording which keys the user set by hand.
_FACTS_USER_EDITED_KEY = "_user_edited"

# Value markers a user edit stamps onto a style_preferences row.
_PREF_USER_EDITED = "user_edited"
_PREF_DELETED = "deleted"

# Confidence a hand-set preference is pinned to (a stated taste is near-certain
# and should sort above inferred ones).
_USER_EDIT_CONFIDENCE = 0.9

# How many active learned preferences the screen shows (by confidence).
_PREF_LIMIT = 24

_TYPED_DIMENSION_SET = frozenset(_TYPED_DIMENSIONS)
_POLARITIES = frozenset({"like", "dislike", "neutral"})


class StyleProfileValidationError(ValueError):
    """A user PATCH payload was malformed (mapped to HTTP 422)."""


# ---------------------------------------------------------------------------
# READ
# ---------------------------------------------------------------------------
def _explain(source: Optional[str], evidence_count: int, user_edited: bool) -> str:
    """A short, honest human line derived from the preference's evidence — what
    Tailor learned this from, so the user can judge it. Never fabricates counts."""
    n = evidence_count or 0
    if user_edited:
        return "You set this yourself"
    if source == "onboarding":
        return "From your onboarding answers"
    if source == "explicit":
        base = "From what you told the stylist"
        return f"{base} · {n} {'mention' if n == 1 else 'mentions'}" if n else base
    if source == "imported":
        return "Imported from your history"
    # inferred (chat/behaviour/outfit feedback distilled into a preference)
    if n >= 1:
        return f"Learned from {n} {'signal' if n == 1 else 'signals'} in your activity"
    return "Learned from your activity"


def _expose_facts(facts: Dict[str, Any]) -> Dict[str, Any]:
    """Project facts down to the whitelist the screen renders."""
    return {k: v for k, v in facts.items() if k in EXPOSED_FACT_KEYS}


def _pref_out(row: StylePreference) -> Dict[str, Any]:
    value = row.value if isinstance(row.value, dict) else {}
    user_edited = bool(value.get(_PREF_USER_EDITED))
    conf = float(row.confidence) if row.confidence is not None else None
    ev = int(row.evidence_count or 0)
    # Never leak the internal provenance markers back out as data.
    public_value = {k: v for k, v in value.items() if k not in (_PREF_USER_EDITED, _PREF_DELETED)}
    return {
        "dimension": row.dimension,
        "value": public_value,
        "polarity": row.polarity,
        "confidence": conf,
        "evidenceCount": ev,
        "source": row.source,
        "userEdited": user_edited,
        "lastReinforcedAt": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "explanation": _explain(row.source, ev, user_edited),
    }


def read_style_profile(db: Session, user_id: UUID) -> Dict[str, Any]:
    """Assemble the /profile/style GET payload for the current user.

    A brand-new user (no style_profiles row) reads back an honestly-empty
    profile — no filler. Only ACTIVE preferences are returned, so tombstoned
    (deleted) rows never surface.
    """
    profile: Optional[StyleProfile] = (
        db.query(StyleProfile).filter(StyleProfile.user_id == user_id).one_or_none()
    )
    facts = dict(profile.facts or {}) if profile is not None else {}
    narrative = dict(profile.narrative_blob or {}) if profile is not None else {}

    rows: List[StylePreference] = (
        db.query(StylePreference)
        .filter(StylePreference.user_id == user_id, StylePreference.active.is_(True))
        .order_by(
            StylePreference.confidence.desc().nullslast(),
            StylePreference.last_seen_at.desc(),
        )
        .limit(_PREF_LIMIT)
        .all()
    )

    return {
        "facts": _expose_facts(facts),
        "narrative": _narrative_text(narrative) or None,
        "summary": profile.summary if profile is not None else None,
        "onboardingCompletedAt": facts.get("onboarding_completed_at"),
        "version": int(profile.version) if profile is not None else 0,
        "preferences": [_pref_out(r) for r in rows],
    }


# ---------------------------------------------------------------------------
# WRITE (no commit — the RLS-scoped session context manager owns it)
# ---------------------------------------------------------------------------
def _get_or_create_profile(db: Session, user_id: UUID) -> StyleProfile:
    profile = db.query(StyleProfile).filter(StyleProfile.user_id == user_id).one_or_none()
    if profile is not None:
        return profile
    profile = StyleProfile(user_id=user_id, facts={})
    db.add(profile)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        profile = db.query(StyleProfile).filter(StyleProfile.user_id == user_id).one()
    return profile


def apply_facts_edit(db: Session, user_id: UUID, facts_partial: Dict[str, Any]) -> None:
    """Merge a whitelisted facts patch into style_profiles.facts and stamp the
    edited keys user-edited. Un-whitelisted / server-owned keys are dropped, so a
    client can never write location, avoid-lists, completion, or body fields here.

    Facts are never touched by distillation, so no distill guard is needed; the
    ``_user_edited`` sidecar is durable provenance (and forward-protection if any
    future writer merges facts).
    """
    clean = sanitize_facts(facts_partial)  # bounded tree, strips onboarding_completed_at
    patch = {k: v for k, v in clean.items() if k in EXPOSED_FACT_KEYS}
    if not patch:
        return

    profile = _get_or_create_profile(db, user_id)
    merged = dict(profile.facts or {})
    merged.update(patch)

    edited = merged.get(_FACTS_USER_EDITED_KEY)
    edited = dict(edited) if isinstance(edited, dict) else {}
    for key in patch:
        edited[key] = True
    merged[_FACTS_USER_EDITED_KEY] = edited

    profile.facts = merged  # reassign so SQLAlchemy flags the JSONB column dirty


def _validate_dimension(dimension: Any) -> str:
    if not isinstance(dimension, str) or dimension not in _TYPED_DIMENSION_SET:
        raise StyleProfileValidationError(
            f"dimension must be one of {sorted(_TYPED_DIMENSION_SET)}"
        )
    return dimension


def apply_preference_override(
    db: Session,
    user_id: UUID,
    dimension: str,
    *,
    polarity: Optional[str],
    value: Optional[Dict[str, Any]],
) -> None:
    """Assert a learned preference by hand (a SACRED write).

    Upserts the (user_id, dimension) row as source='explicit', active=True,
    high confidence, and stamps ``value.user_edited=True`` so distillation freezes
    it. Clearing a previously-tombstoned dimension by overriding it re-activates.
    """
    dim = _validate_dimension(dimension)
    if polarity is not None and polarity not in _POLARITIES:
        raise StyleProfileValidationError(f"polarity must be one of {sorted(_POLARITIES)}")
    clean_value = _sanitize_json(value or {}, field="preferences[].value", depth=0)
    if not isinstance(clean_value, dict):
        raise StyleProfileValidationError("preferences[].value must be an object")
    clean_value[_PREF_USER_EDITED] = True

    now = datetime.now(timezone.utc)
    row = (
        db.query(StylePreference)
        .filter(StylePreference.user_id == user_id, StylePreference.dimension == dim)
        .one_or_none()
    )
    if row is None:
        db.add(
            StylePreference(
                user_id=user_id,
                dimension=dim,
                value=clean_value,
                polarity=polarity,
                confidence=_USER_EDIT_CONFIDENCE,
                source="explicit",
                active=True,
                evidence_count=0,
                last_seen_at=now,
            )
        )
        return
    row.value = clean_value
    row.polarity = polarity
    row.source = "explicit"
    row.active = True
    row.confidence = max(float(row.confidence or 0.0), _USER_EDIT_CONFIDENCE)
    row.last_seen_at = now


def tombstone_preference(db: Session, user_id: UUID, dimension: str) -> None:
    """Forget a learned preference for good.

    Keeps the row (does NOT delete it) so the UNIQUE(user_id, dimension) slot stays
    occupied by a frozen tombstone: active=False, source='explicit', and
    ``value.user_edited = value.deleted = True``. Distillation's recompute skips any
    user-locked row, so old preference_signals can never re-emerge this dimension.
    A tombstone is created even if no preference row existed yet (the dimension may
    live only as raw signals not yet distilled).
    """
    dim = _validate_dimension(dimension)
    now = datetime.now(timezone.utc)
    row = (
        db.query(StylePreference)
        .filter(StylePreference.user_id == user_id, StylePreference.dimension == dim)
        .one_or_none()
    )
    tomb = {_PREF_USER_EDITED: True, _PREF_DELETED: True}
    if row is None:
        db.add(
            StylePreference(
                user_id=user_id,
                dimension=dim,
                value=tomb,
                polarity=None,
                confidence=None,
                source="explicit",
                active=False,
                evidence_count=0,
                last_seen_at=now,
            )
        )
        return
    existing = dict(row.value) if isinstance(row.value, dict) else {}
    existing.update(tomb)
    row.value = existing
    row.active = False
    row.source = "explicit"
    row.last_seen_at = now
