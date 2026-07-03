"""Onboarding seed: the write path from the S1 tap-only onboarding into the S0
Style Profile substrate (``style_profiles.facts``, ``style_preferences``,
``preference_signals``).

Wave S1. The 6-screen onboarding stages its answers client-side and commits ONCE
via ``POST /onboarding/seed`` (see app/api/routes/onboarding.py). This module owns
the DB writes; the route owns the transaction boundary (mirrors events_service /
events.py). Nothing here commits.

SECURITY / ABUSE GUARDS (this writes personal profile data):
  * ``user_id`` is ALWAYS the JWT subject, never read from a request body.
  * ``source`` is FORCED to 'onboarding' on every preference/signal — the client
    cannot spoof provenance.
  * ``confidence`` is CLAMPED into the onboarding band [MIN, MAX] regardless of the
    client value — a self-reported taste is a weak prior, never certainty.
  * ``polarity`` is enum-validated against the DB CHECK set; bad values -> 422.
  * typed columns (dimension, signal_type, polarity, source) never receive raw
    free-text blobs — free-form data only lands in the sanitized jsonb ``value`` /
    ``facts`` fields, which are depth/size/key capped.
  * ``onboarding_completed_at`` is stamped SERVER-SIDE after merge; a client-sent
    value is stripped, so completion can't be forged in the facts payload.
  * cross-user refs are impossible: client-supplied item_id/event_id are ignored
    (onboarding taste swipes reference archetype imagery, not owned rows).
  * re-running onboarding is idempotent: the profile is upserted (UNIQUE user_id)
    and preferences upsert on (user_id, dimension) — a second seed never 409s.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import PreferenceSignal, StylePreference, StyleProfile

logger = logging.getLogger(__name__)

# The provenance stamp on every onboarding-seeded row. Matches the DB CHECK
# constraints on style_preferences.source and preference_signals.source.
ONBOARDING_SOURCE = "onboarding"

# DB CHECK set shared by both tables' polarity column.
_POLARITIES = frozenset({"like", "dislike", "neutral"})

# facts jsonb sanitation bounds (depth-limited, small, JSON-safe). Mirrors the
# events_service properties guard: this is both a size guard and a PII guard —
# free-form nested blobs are where addresses / email bodies would leak in.
_ALLOWED_SCALARS = (str, int, float, bool, type(None))
_MAX_FACTS_KEYS = 32          # keys per object level
_MAX_FACTS_DEPTH = 4          # nesting depth
_MAX_LIST_LEN = 64            # items per array
_MAX_STR_LEN = 512            # chars per string
# Server-owned facts key; stripped from client input, stamped after merge.
_COMPLETED_AT_KEY = "onboarding_completed_at"

# Typed-column string caps (dimension / signal_type / key).
_MAX_DIMENSION_LEN = 128
_MAX_SIGNAL_TYPE_LEN = 128
_MAX_KEY_LEN = 256
_MAX_EVIDENCE_REF_LEN = 256


class OnboardingValidationError(ValueError):
    """Raised when an untrusted seed payload fails validation. The message names
    only field/enum problems — never echoes payload content — so it is safe to
    surface to the caller as an HTTP 422 detail."""


# ---------------------------------------------------------------------------
# Sanitation
# ---------------------------------------------------------------------------
def _sanitize_json(value: Any, *, field: str, depth: int) -> Any:
    """Coerce an arbitrary value into a bounded, JSON-safe tree.

    dict/list nesting capped at _MAX_FACTS_DEPTH; <= _MAX_FACTS_KEYS keys per
    object; <= _MAX_LIST_LEN list items; strings truncated to _MAX_STR_LEN;
    leaves must be JSON scalars. Raises OnboardingValidationError.
    """
    if isinstance(value, _ALLOWED_SCALARS):
        return value[:_MAX_STR_LEN] if isinstance(value, str) else value
    if depth >= _MAX_FACTS_DEPTH:
        raise OnboardingValidationError(f"{field} nested too deeply")
    if isinstance(value, dict):
        if len(value) > _MAX_FACTS_KEYS:
            raise OnboardingValidationError(f"{field} has too many keys (max {_MAX_FACTS_KEYS})")
        clean: Dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise OnboardingValidationError(f"{field} keys must be strings")
            clean[k[:_MAX_STR_LEN]] = _sanitize_json(v, field=field, depth=depth + 1)
        return clean
    if isinstance(value, list):
        if len(value) > _MAX_LIST_LEN:
            raise OnboardingValidationError(f"{field} list too long (max {_MAX_LIST_LEN})")
        return [_sanitize_json(v, field=f"{field}[]", depth=depth + 1) for v in value]
    raise OnboardingValidationError(f"{field} must be JSON-safe (object/array/scalar)")


def sanitize_facts(facts: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Validate the untrusted facts object: bounded tree + serialized-size cap.

    Strips the server-owned _COMPLETED_AT_KEY so a client cannot forge completion.
    Raises OnboardingValidationError.
    """
    if facts is None:
        return {}
    if not isinstance(facts, dict):
        raise OnboardingValidationError("facts must be an object")
    facts = {k: v for k, v in facts.items() if k != _COMPLETED_AT_KEY}
    clean = _sanitize_json(facts, field="facts", depth=0)
    # Serialized-size ceiling (defends against many-small-keys within the caps).
    encoded = json.dumps(clean, separators=(",", ":"), default=str)
    if len(encoded.encode("utf-8")) > settings.ONBOARDING_MAX_FACTS_BYTES:
        raise OnboardingValidationError(
            f"facts exceeds {settings.ONBOARDING_MAX_FACTS_BYTES} bytes"
        )
    return clean


def _clamp_confidence(value: Any) -> float:
    """Clamp a client confidence into the onboarding band. Absent/invalid -> band
    midpoint. Onboarding taste is never certainty, so the band is narrow."""
    lo, hi = settings.ONBOARDING_CONFIDENCE_MIN, settings.ONBOARDING_CONFIDENCE_MAX
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return round((lo + hi) / 2, 4)
    return float(min(hi, max(lo, value)))


def _validate_polarity(value: Any, *, field: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or value not in _POLARITIES:
        raise OnboardingValidationError(f"{field} must be one of {sorted(_POLARITIES)}")
    return value


def _require_str(value: Any, *, field: str, max_len: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OnboardingValidationError(f"{field} is required and must be a non-empty string")
    return value.strip()[:max_len]


def _clamp_weight(value: Any) -> Optional[float]:
    """Signal weight -> [0, 1] float, or None. Bounds an arbitrary client number."""
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise OnboardingValidationError("weight must be a number")
    return float(min(1.0, max(0.0, value)))


# ---------------------------------------------------------------------------
# Write path (no commit — the route owns the transaction)
# ---------------------------------------------------------------------------
def seed_style_profile(db: Session, user_id: UUID, facts: Dict[str, Any]) -> StyleProfile:
    """Upsert the user's style_profiles row, merging ``facts`` and stamping
    completion server-side. UNIQUE(user_id) makes this idempotent across re-runs.

    ``facts`` must already be sanitized (see :func:`sanitize_facts`).
    """
    completed_at = datetime.now(timezone.utc).isoformat()
    profile = db.query(StyleProfile).filter(StyleProfile.user_id == user_id).one_or_none()

    if profile is None:
        merged = dict(facts)
        merged[_COMPLETED_AT_KEY] = completed_at
        profile = StyleProfile(user_id=user_id, facts=merged)
        db.add(profile)
        try:
            db.flush()
        except IntegrityError:
            # Concurrent first-seed for the same user; fall through to update.
            db.rollback()
            profile = (
                db.query(StyleProfile).filter(StyleProfile.user_id == user_id).one()
            )
            merged = dict(profile.facts or {})
            merged.update(facts)
            merged[_COMPLETED_AT_KEY] = completed_at
            profile.facts = merged
    else:
        merged = dict(profile.facts or {})
        merged.update(facts)
        merged[_COMPLETED_AT_KEY] = completed_at
        # Reassign (not in-place mutate) so SQLAlchemy flags the JSONB column dirty.
        profile.facts = merged

    return profile


def seed_style_preferences(
    db: Session, user_id: UUID, preferences: List[Dict[str, Any]]
) -> int:
    """Upsert each preference on (user_id, dimension). source is forced to
    'onboarding' and confidence is clamped to the onboarding band. Returns count.

    Each dict: {dimension: str, value?: obj, polarity?: str, confidence?: num}.
    """
    count = 0
    for pref in preferences:
        dimension = _require_str(
            pref.get("dimension"), field="preferences[].dimension", max_len=_MAX_DIMENSION_LEN
        )
        value = _sanitize_json(pref.get("value") or {}, field="preferences[].value", depth=0)
        if not isinstance(value, dict):
            raise OnboardingValidationError("preferences[].value must be an object")
        polarity = _validate_polarity(pref.get("polarity"), field="preferences[].polarity")
        confidence = _clamp_confidence(pref.get("confidence"))

        row = (
            db.query(StylePreference)
            .filter(
                StylePreference.user_id == user_id,
                StylePreference.dimension == dimension,
            )
            .one_or_none()
        )
        now = datetime.now(timezone.utc)
        if row is None:
            row = StylePreference(
                user_id=user_id,
                dimension=dimension,
                value=value,
                polarity=polarity,
                confidence=confidence,
                source=ONBOARDING_SOURCE,
                evidence_count=1,
                last_seen_at=now,
            )
            db.add(row)
            try:
                db.flush()
            except IntegrityError:
                # Concurrent insert of the same (user, dimension); switch to update.
                db.rollback()
                row = (
                    db.query(StylePreference)
                    .filter(
                        StylePreference.user_id == user_id,
                        StylePreference.dimension == dimension,
                    )
                    .one()
                )
                _apply_pref_update(row, value, polarity, confidence, now)
        else:
            _apply_pref_update(row, value, polarity, confidence, now)
        count += 1
    return count


def _apply_pref_update(
    row: StylePreference,
    value: Dict[str, Any],
    polarity: Optional[str],
    confidence: float,
    now: datetime,
) -> None:
    """Re-assert an existing preference from a fresh onboarding answer."""
    row.value = value
    row.polarity = polarity
    row.confidence = confidence
    row.source = ONBOARDING_SOURCE
    row.evidence_count = (row.evidence_count or 0) + 1
    row.last_seen_at = now


def seed_preference_signals(
    db: Session, user_id: UUID, signals: List[Dict[str, Any]]
) -> int:
    """Append preference_signals rows (append-only). source and evidence_ref are
    forced to 'onboarding'; item_id/event_id are never taken from the client.
    Returns count.

    Each dict: {signalType: str, key?: str, value?: obj, polarity?: str, weight?: num}.
    """
    count = 0
    for sig in signals:
        signal_type = _require_str(
            sig.get("signalType") or sig.get("signal_type"),
            field="signals[].signalType",
            max_len=_MAX_SIGNAL_TYPE_LEN,
        )
        key_raw = sig.get("key")
        key = (
            _require_str(key_raw, field="signals[].key", max_len=_MAX_KEY_LEN)
            if key_raw is not None
            else None
        )
        value = sig.get("value")
        value = (
            _sanitize_json(value, field="signals[].value", depth=0)
            if value is not None
            else None
        )
        polarity = _validate_polarity(sig.get("polarity"), field="signals[].polarity")
        weight = _clamp_weight(sig.get("weight"))

        row = PreferenceSignal(
            user_id=user_id,
            signal_type=signal_type,
            key=key,
            value=value,
            polarity=polarity,
            weight=weight,
            source=ONBOARDING_SOURCE,
            evidence_ref=ONBOARDING_SOURCE,
            # item_id / event_id deliberately left NULL — never trusted from a
            # client payload (no cross-user references).
        )
        db.add(row)
        count += 1
    return count


# ---------------------------------------------------------------------------
# Read path (completion gate)
# ---------------------------------------------------------------------------
def onboarding_completed(db: Session, user_id: UUID) -> bool:
    """True once the user's style_profiles.facts carries onboarding_completed_at."""
    profile = (
        db.query(StyleProfile.facts)
        .filter(StyleProfile.user_id == user_id)
        .one_or_none()
    )
    if profile is None:
        return False
    facts = profile[0] or {}
    return bool(isinstance(facts, dict) and facts.get(_COMPLETED_AT_KEY))
