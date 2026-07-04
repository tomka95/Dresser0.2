"""Attribute-level credit assignment for outfit feedback (Wave S3 learning loop).

The outfit surfaces (chat composer) let a user REJECT, MODIFY (swap a slot), or
mark an outfit WORN. Each reaction is telemetry (a ``style_events`` row, written by
the route) AND a learning signal: this module fans the reaction out to per-ITEM,
per-ATTRIBUTE ``preference_signals`` so the s3a distill/redistill pipeline can turn
it into typed ``style_preferences``.

WHY per-attribute: an outfit is a bundle. "Too dressy" is about its FORMALITY, not
its colors; swapping black loafers for white sneakers is a statement about COLOR and
CATEGORY, not about the shirt that stayed. Crediting the whole bundle would smear a
sharp signal across every item. So:

  * REJECT + reason chips -> a dislike on the chip's dimension, scoped to the items
    that actually carry it (color chip -> the non-neutral colors present; formality
    chip -> one outfit-level formality dislike; item-specific -> that item's attrs).
  * MODIFY (swap) -> the PRECISE signal: compare the removed item and its replacement
    attribute-by-attribute; every axis where they DIFFER yields a dislike on the
    removed value and a like on the replacement value. Axes they share say nothing.
  * WORN / ACCEPT -> reinforce the combination: a mild like on each kept item's
    salient attributes.

Every signal is written with ``source='outfit_feedback'`` — which the distill
recompute weights ABOVE inferred (behavior/chat_inferred) and BELOW user-stated
(onboarding/chat_explicit), exactly the requested precedence (see distill._SOURCE_WEIGHT).
Only CANONICAL typed dimensions are ever keyed (distill.DIMENSIONS), so a signal can
never pollute the profile with a free-text axis.

SECURITY / PRIVACY: ``user_id`` is the caller's responsibility (always a JWT subject).
Items MUST be pre-validated as the caller's own (the route resolves them through
retrieval.get_owned_items). ``note`` carries only garment attribute values (a color
name, a formality integer) — never message text, names, or free-form user input.
Nothing here commits; the caller owns the transaction.
"""
from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import ClothingItem, PreferenceSignal
from app.services.stylist.composer import _NEUTRALS

logger = logging.getLogger(__name__)

# preference_signals.source + signal_type stamped on every row this module writes.
FEEDBACK_SOURCE = "outfit_feedback"
SIGNAL_TYPE = "outfit_feedback"

# The reason chips the reject surface offers. WEATHER is deliberately NOT mapped to a
# durable dimension: "wrong for the weather" is situational appropriateness, not a
# standing taste, so it is logged as an event but produces no preference signal.
REASON_CHIPS = frozenset(
    {"color", "formality", "weather", "not_my_style", "fit", "item_specific"}
)
# Optional directional refinement a reject chip may carry (recorded in the note for
# the narrative; polarity is always "dislike" for a reject).
REASON_DIRECTIONS = frozenset(
    {"too_formal", "too_casual", "too_warm", "too_cold", "too_tight", "too_loose"}
)

# clothing_items attribute -> canonical distill dimension. Drives modify-diff and the
# salient-attribute fan-out for reinforce / item-specific reject. Every dimension here
# is one of distill.DIMENSIONS, so the recompute aggregates them into typed prefs.
_ATTR_DIMS = (
    ("color_primary", "color"),
    ("formality", "formality"),
    ("pattern", "pattern"),
    ("material", "material"),
    ("fit_silhouette", "silhouette"),
    ("sub_category", "category"),
    ("brand", "brand"),
    ("length", "length"),
)

# Signal strengths (all <= 1; the recompute further scales by the 0.7 source weight).
_W_REJECT = 0.5        # generic outfit-level reject dislike
_W_REJECT_ITEM = 0.75  # item-specific reject — the user pointed at ONE piece (precise)
_W_SWAP = 0.7          # modify: the user actively replaced one thing with another
_W_REINFORCE = 0.4     # accept / worn — a real-world thumbs-up, but diffuse

_MAX_NOTE = 160


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _is_neutral_color(value: object) -> bool:
    return isinstance(value, str) and value.strip().lower() in _NEUTRALS


def _non_neutral_color(item: ClothingItem) -> Optional[str]:
    col = (item.color_primary or "").strip()
    if not col or _is_neutral_color(col):
        return None
    return col


def _norm(value: object) -> Optional[str]:
    """Comparable, lowercased key for an attribute value (None -> None)."""
    if value is None:
        return None
    s = str(value).strip().lower()
    return s or None


def _fmt(dimension: str, value: object) -> str:
    """Short, PII-free note describing an attribute value (audit / narrative only)."""
    if dimension == "formality":
        return f"formality {value}"
    return str(value)[:_MAX_NOTE]


def _mk_signal(
    user_id: UUID,
    *,
    dimension: str,
    polarity: str,
    weight: float,
    item_id: Optional[UUID] = None,
    note: Optional[str] = None,
    event_id: Optional[UUID] = None,
    evidence_ref: Optional[str] = None,
) -> PreferenceSignal:
    return PreferenceSignal(
        user_id=user_id,
        signal_type=SIGNAL_TYPE,
        key=dimension,
        value={"note": note[:_MAX_NOTE]} if note else None,
        polarity=polarity,
        weight=float(min(1.0, max(0.0, weight))),
        item_id=item_id,
        event_id=event_id,
        source=FEEDBACK_SOURCE,
        evidence_ref=evidence_ref,
    )


def _salient_signals(
    user_id: UUID,
    item: ClothingItem,
    *,
    polarity: str,
    weight: float,
    event_id: Optional[UUID],
) -> List[PreferenceSignal]:
    """One signal per known salient attribute of ``item`` (skipping neutral colors)."""
    out: List[PreferenceSignal] = []
    for attr, dim in _ATTR_DIMS:
        val = getattr(item, attr, None)
        if val is None or (isinstance(val, str) and not val.strip()):
            continue
        if dim == "color" and _is_neutral_color(val):
            continue  # neutrals carry no palette taste
        out.append(_mk_signal(
            user_id, dimension=dim, polarity=polarity, weight=weight,
            item_id=item.id, note=_fmt(dim, val), event_id=event_id,
        ))
    return out


# ---------------------------------------------------------------------------
# Public credit-assignment entry points. Each ADDS rows to the session (no commit)
# and returns them so the caller can count / summarize.
# ---------------------------------------------------------------------------
def apply_reject(
    db: Session,
    user_id: UUID,
    items: Iterable[ClothingItem],
    *,
    reason_chips: Iterable[str],
    directions: Optional[Dict[str, str]] = None,
    item_specific: Optional[ClothingItem] = None,
    event_id: Optional[UUID] = None,
) -> List[PreferenceSignal]:
    """Fan a rejected outfit + its reason chips into per-item dislike signals."""
    directions = directions or {}
    items = list(items)
    out: List[PreferenceSignal] = []

    for chip in reason_chips:
        if chip not in REASON_CHIPS:
            continue
        if chip == "color":
            for it in items:
                col = _non_neutral_color(it)
                if col:
                    out.append(_mk_signal(
                        user_id, dimension="color", polarity="dislike",
                        weight=_W_REJECT, item_id=it.id, note=col, event_id=event_id))
        elif chip == "formality":
            direction = directions.get("formality")
            note = direction if direction in REASON_DIRECTIONS else "off"
            out.append(_mk_signal(
                user_id, dimension="formality", polarity="dislike",
                weight=_W_REJECT, note=note, event_id=event_id))
        elif chip == "fit":
            for it in items:
                fs = (it.fit_silhouette or "").strip() or None
                out.append(_mk_signal(
                    user_id, dimension="fit", polarity="dislike",
                    weight=_W_REJECT, item_id=it.id, note=fs, event_id=event_id))
        elif chip == "not_my_style":
            out.append(_mk_signal(
                user_id, dimension="vibe", polarity="dislike",
                weight=_W_REJECT, note="not my style", event_id=event_id))
        elif chip == "weather":
            # Situational appropriateness, not a durable taste — no preference signal.
            continue
        elif chip == "item_specific" and item_specific is not None:
            out.extend(_salient_signals(
                user_id, item_specific, polarity="dislike",
                weight=_W_REJECT_ITEM, event_id=event_id))

    for s in out:
        db.add(s)
    return out


def apply_modify(
    db: Session,
    user_id: UUID,
    removed: ClothingItem,
    replacement: ClothingItem,
    *,
    kept: Optional[Iterable[ClothingItem]] = None,
    event_id: Optional[UUID] = None,
) -> List[PreferenceSignal]:
    """Precise swap credit: on every attribute where the removed item and its
    replacement DIFFER, dislike the removed value + like the replacement value.
    Shared attributes are left untouched (the swap said nothing about them). Kept
    items are mildly reinforced (they survived the edit)."""
    out: List[PreferenceSignal] = []
    for attr, dim in _ATTR_DIMS:
        a = getattr(removed, attr, None)
        b = getattr(replacement, attr, None)
        a_key, b_key = _norm(a), _norm(b)
        if a_key is None and b_key is None:
            continue
        if a_key is not None and a_key == b_key:
            continue  # identical on this axis — not what the user changed
        if a_key is not None and not (dim == "color" and _is_neutral_color(a)):
            out.append(_mk_signal(
                user_id, dimension=dim, polarity="dislike", weight=_W_SWAP,
                item_id=removed.id, note=_fmt(dim, a), event_id=event_id))
        if b_key is not None and not (dim == "color" and _is_neutral_color(b)):
            out.append(_mk_signal(
                user_id, dimension=dim, polarity="like", weight=_W_SWAP,
                item_id=replacement.id, note=_fmt(dim, b), event_id=event_id))

    for it in (kept or []):
        out.extend(_salient_signals(
            user_id, it, polarity="like", weight=_W_REINFORCE, event_id=event_id))

    for s in out:
        db.add(s)
    return out


def apply_reinforce(
    db: Session,
    user_id: UUID,
    items: Iterable[ClothingItem],
    *,
    event_id: Optional[UUID] = None,
    weight: float = _W_REINFORCE,
    polarity: str = "like",
) -> List[PreferenceSignal]:
    """Reinforce a worn / accepted combination: a mild like on every item's
    salient attributes. This is the accept+worn half of the loop."""
    out: List[PreferenceSignal] = []
    for it in items:
        out.extend(_salient_signals(
            user_id, it, polarity=polarity, weight=weight, event_id=event_id))
    for s in out:
        db.add(s)
    return out
