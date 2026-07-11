"""Today's Look — one auto-composed outfit for the day, shown on Home open.

This is the deterministic spine behind ``GET /todays-look`` and its ``/remix``
sibling. It mirrors the stylist ``compose_outfit`` tool (tools.py:_tool_compose_outfit)
but with NO model in the loop at any point:

  * weather  -> ``forecast_for_facts`` gives a warmth band (1 hot..3 cold) that
    feeds the composer's ``warmth_target``;
  * calendar -> ``assemble_calendar`` derives an OCCASION + FORMALITY server-side.
    Only the derived occasion/formality cross into here; raw event titles are
    NEVER read or persisted by this module;
  * profile  -> ``assemble_profile`` (hard avoids, preferences) as always;
  * compose  -> the pure, rule-based ``compose_outfit`` (unchanged; chat depends on
    its honest-gap filtering) driven through a Today's-Look-only STEP-DOWN loop;
  * collage  -> ``get_or_create_grid_collage``: every item knocked out on ONE
    pure-white field, side by side (pure PIL, no image API).

WHY THE STEP-DOWN (formality-adaptive composition, localized here — compose_outfit
is untouched): a calendar can derive a formality target (e.g. "work" -> 4) that no
outfit in a casual closet can satisfy — every real piece falls outside the ±1
formality band and the composer honestly reports gaps. For a passive Home surface
that reads as an empty "starter" even though the user HAS a complete casual set. So
here we:

  1. try the derived formality, and if a required slot is unfilled, step the target
     DOWN (highest-first) until a COMPLETE look is found — preferring the highest
     formality that still completes, only falling back to "starter" if NO formality
     completes;
  2. PREFER owned real photos: a first pass excludes image-less rows (receipt junk
     with no usable photo) so real pieces win slots; only if that can't complete do
     we allow image-less items back in;
  3. EXCLUDE undergarments / bags / hair accessories from being primaries — they
     are never a valid "today's look".

A complete look is returned as ``kind="normal"`` even when it sits below the day's
ideal formality (the caption may note it); only a genuinely un-completable closet
yields ``kind="starter"``.

FAILURE POSTURE: weather, calendar and collage are each best-effort — any failing
degrades the look but NEVER raises (Home must not 500 on a flaky provider).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import ClothingItem
from app.services.stylist.calendar import CalendarBlock, assemble_calendar
from app.services.stylist.collage import get_or_create_grid_collage, usable_image_url
from app.services.stylist.composer import ComposedOutfit, _slot_of, compose_outfit
from app.services.stylist.profile import ProfileBlock, assemble_profile
from app.services.stylist.retrieval import serialize_item

try:  # weather is optional infra; import must never hard-fail the module
    from app.services.weather.service import forecast_for_facts
except Exception:  # pragma: no cover - defensive
    forecast_for_facts = None  # type: ignore

logger = logging.getLogger(__name__)

# Cell order in the title/collage: silhouette first, then finishing pieces.
_SLOT_ORDER = ("outerwear", "top", "dress", "bottom", "footwear", "accessory")


# ---------------------------------------------------------------------------
# Candidate steering (Today's-Look-local; compose_outfit stays default)
# ---------------------------------------------------------------------------
# Items that are never a valid standalone "today's look" primary. Matched
# case-insensitively as substrings across name + sub_category + category.
_UNDERGARMENT_TOKENS = (
    "bra", "bralette", "thong", "panty", "panties", "brief", "boxer",
    "underwear", "lingerie", "undershirt", "camisole",
)
_NON_GARMENT_ACCESSORY_TOKENS = (
    "handbag", "hand bag", "purse", "clutch", "tote", "wallet", "lunch bag",
    "hair clip", "hairclip", "hairpin", "barrette", "claw clip", "scrunchie",
    "hair accessory", "hair barrette",
)
_NON_GARMENT_SUBCATS = frozenset(
    {"tote_bag", "handbag", "purse", "clutch", "wallet"}
)


def _is_non_primary(item: ClothingItem) -> bool:
    """True for undergarments, bags and hair accessories — excluded from being a
    Today's Look primary (they still live in the closet; just never auto-styled)."""
    if (item.sub_category or "") in _NON_GARMENT_SUBCATS:
        return True
    hay = f"{item.name or ''} {item.sub_category or ''} {item.category or ''}".lower()
    return any(tok in hay for tok in _UNDERGARMENT_TOKENS) or any(
        tok in hay for tok in _NON_GARMENT_ACCESSORY_TOKENS
    )


def _load_owned(db: Session, user_id: UUID) -> List[ClothingItem]:
    return (
        db.query(ClothingItem)
        .filter(ClothingItem.user_id == user_id, ClothingItem.archived_at.is_(None))
        .all()
    )


def _formality_ladder(derived: Optional[int]) -> List[Optional[int]]:
    """Targets to try, highest-first. None (no calendar target) means one pass with
    the composer's formality constraint off. Otherwise step DOWN to 1."""
    if derived is None:
        return [None]
    top = max(1, min(5, int(derived)))
    return list(range(top, 0, -1))  # e.g. 4 -> [4, 3, 2, 1]


@dataclass
class _Composed:
    outfit: ComposedOutfit
    used_formality: Optional[int]
    below_ideal: bool


def _compose_best(
    db: Session,
    user_id: UUID,
    profile: ProfileBlock,
    *,
    warmth: Optional[int],
    occasion: Optional[str],
    derived_formality: Optional[int],
    request_exclude: Set[UUID],
    owned: List[ClothingItem],
) -> _Composed:
    """Formality step-down × real-photo preference. Returns the highest-formality
    COMPLETE look reachable with real photos; falls back to allowing image-less
    items, then to the best partial (starter). compose_outfit itself is unchanged —
    we only steer it via exclude sets and retry at lower formality."""
    non_primary = {it.id for it in owned if _is_non_primary(it)}
    imageless = {it.id for it in owned if usable_image_url(it) is None}
    base_exclude = set(request_exclude) | non_primary
    ladder = _formality_ladder(derived_formality)

    best_partial: Optional[_Composed] = None
    # Pass 1 prefers real owned photos (drop image-less rows); pass 2 allows them.
    for real_only in (True, False):
        exclude = base_exclude | (imageless if real_only else set())
        for target in ladder:
            outfit = compose_outfit(
                db, user_id, profile,
                occasion=occasion,
                formality_target=target,
                warmth_target=warmth,
                exclude_item_ids=list(exclude),
            )
            if outfit.slots and not outfit.gaps:
                below = (
                    derived_formality is not None
                    and target is not None
                    and target < derived_formality
                )
                return _Composed(outfit, target, below)
            if best_partial is None and outfit.slots:
                best_partial = _Composed(outfit, target, False)

    if best_partial is not None:
        return best_partial
    # Nothing placed at all — a coherent (empty) starter at the derived target.
    outfit = compose_outfit(
        db, user_id, profile,
        occasion=occasion, formality_target=derived_formality, warmth_target=warmth,
        exclude_item_ids=list(base_exclude),
    )
    return _Composed(outfit, derived_formality, False)


# ---------------------------------------------------------------------------
# Deterministic caption (occasion phrase + weather-aware layer line). No model.
# ---------------------------------------------------------------------------
_OCCASION_LEAD = {
    "a formal event": "Dressed to the nines.",
    "an interview": "Interview-ready.",
    "work": "Meeting-sharp.",
    "dinner out": "Dinner-ready.",
    "something casual": "Easy and off-duty.",
    "the gym": "Ready to move.",
}
_DEFAULT_LEAD = "Put-together for whatever today holds."

_WARMTH_LAYER = {
    1: "Skip the layers.",
    2: "Coat optional.",
    3: "Layer up — it's cold out.",
}


def _caption(
    occasion: Optional[str], warmth: Optional[int], wet: bool, below_ideal: bool
) -> str:
    """Two-clause caption, plus a gentle note when the look sits below the day's
    ideal formality (still a complete look — never a refusal)."""
    lead = _OCCASION_LEAD.get(occasion or "", _DEFAULT_LEAD)
    if wet:
        layer = "Rain's likely — bring a shell."
    elif warmth in _WARMTH_LAYER:
        layer = _WARMTH_LAYER[warmth]
    else:
        layer = ""
    caption = f"{lead} {layer}".strip()
    if below_ideal:
        caption = f"{caption}  Casual-day pick — say the word if you want it sharper.".strip()
    return caption


def _title(items: List[Dict[str, Any]]) -> str:
    names = [str(it.get("name") or "").strip() for it in items]
    names = [n for n in names if n]
    return ", ".join(names)


def _ordered_items(outfit: ComposedOutfit) -> List[tuple]:
    order = {s: i for i, s in enumerate(_SLOT_ORDER)}
    return sorted(outfit.slots.items(), key=lambda kv: order.get(kv[0], 99))


# ---------------------------------------------------------------------------
# Derived factors (also drive the half-daily cache signature in the route)
# ---------------------------------------------------------------------------
@dataclass
class Factors:
    warmth: Optional[int] = None
    wet: bool = False
    occasion: Optional[str] = None
    formality_target: Optional[int] = None
    timezone: Optional[str] = None


def _read_weather(facts: Dict[str, Any]) -> tuple:
    """(warmth_band, wet, forecast-or-None). Best-effort — never raises."""
    if forecast_for_facts is None:
        return None, False, None
    try:
        forecast = forecast_for_facts(facts)
    except Exception as exc:  # noqa: BLE001 — weather must never break the look
        logger.warning("todays_look weather read failed: %s", type(exc).__name__)
        return None, False, None
    if forecast is None:
        return None, False, None
    wet = False
    try:
        wet = (forecast.current.precip_mm or 0) > 0 or (
            (forecast.today.precip_chance_pct or 0) >= 50
        )
    except Exception:  # pragma: no cover - defensive
        wet = False
    return forecast.warmth_band, wet, forecast


def _read_calendar(
    db: Session, user_id: UUID, no_persist: bool, facts: Optional[Dict[str, Any]] = None
) -> CalendarBlock:
    """Derived occasion/formality only (TODAY's, in the user's tz). Best-effort —
    never raises."""
    try:
        return assemble_calendar(db, user_id, no_persist=no_persist, facts=facts)
    except Exception as exc:  # noqa: BLE001
        logger.warning("todays_look calendar read failed: %s", type(exc).__name__)
        return CalendarBlock()


def derive_factors(
    db: Session, user_id: UUID, profile: ProfileBlock, *, no_persist: bool = False
) -> Factors:
    """The live factors behind a look: warmth band + wet + derived occasion/
    formality + the user's timezone (for the half-day cache bucket). Cheap reads
    (weather is cache-backed; calendar is a short live fetch)."""
    warmth, wet, forecast = _read_weather(profile.facts)
    tz = getattr(forecast, "timezone", None) if forecast is not None else None
    cal = _read_calendar(db, user_id, no_persist, profile.facts)
    return Factors(
        warmth=warmth, wet=wet,
        occasion=cal.occasion, formality_target=cal.formality_target,
        timezone=tz,
    )


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------
@dataclass
class TodaysLook:
    kind: str  # "normal" (complete) | "starter" (no completable look at any formality)
    outfit: ComposedOutfit
    items: List[Dict[str, Any]] = field(default_factory=list)
    item_ids: List[str] = field(default_factory=list)
    collage_url: Optional[str] = None
    title: str = ""
    caption: str = ""
    occasion: Optional[str] = None
    warmth: Optional[int] = None
    formality: Optional[int] = None
    note: Optional[str] = None

    def to_payload(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "itemIds": list(self.item_ids),
            "items": list(self.items),
            "collageUrl": self.collage_url,
            "title": self.title,
            "caption": self.caption,
            "occasion": self.occasion,
            "warmth": self.warmth,
            "formality": self.formality,
            "note": self.note,
            "rationale": self.outfit.rationale,
        }


_STARTER_NOTE = (
    "Add a few more pieces and Tailor can build you a full look for the day."
)
# Additive completing nudge for a based look that owns no shoes — never a blocker.
_SHOE_NUDGE = "Add shoes to finish the look."


def _has_wearable_base(outfit: ComposedOutfit) -> bool:
    """The minimum that reads as an outfit: a dress on its own, OR a top+bottom pair.

    Today's Look treats FOOTWEAR AS OPTIONAL — many real closets own zero shoes — so a
    based look whose ONLY remaining gap is footwear is still a complete look. Every
    other missing required slot (a base half) still blocks. This rule is LOCAL to
    Today's Look; the shared ``compose_outfit`` stays strict about footwear gaps so
    chat keeps reporting them honestly (see module docstring)."""
    slots = set(outfit.slots)
    return "dress" in slots or {"top", "bottom"} <= slots


def _item_payload(item) -> Dict[str, Any]:
    """serialize_item + an explicit hasImage flag (usable, showable photo)."""
    payload = serialize_item(item)
    payload["hasImage"] = usable_image_url(item) is not None
    return payload


def _finalize(
    user_id: UUID,
    composed: _Composed,
    factors: Factors,
    no_persist: bool,
    *,
    extra_note: Optional[str] = None,
) -> TodaysLook:
    """Build the response object from a composed result — kind, collage, title,
    caption. Shared by GET and Remix so their kind/collage rules match exactly."""
    outfit = composed.outfit
    ordered = _ordered_items(outfit)
    items = [_item_payload(it) for _slot, it in ordered]
    item_ids = [str(it.id) for _slot, it in ordered]

    # Completeness — not "sufficient" (which folds in occasion-fit confidence).
    # A complete look below the day's ideal formality is STILL a real look. Footwear
    # is OPTIONAL here: a wearable base (dress, or top+bottom) with ONLY a footwear gap
    # is a real look; a missing base half (or no items) is a starter.
    based = _has_wearable_base(outfit)
    non_footwear_gaps = [g for g in outfit.gaps if g != "footwear"]
    starter = (not outfit.slots) or (not based) or bool(non_footwear_gaps)
    kind = "starter" if starter else "normal"

    collage_url: Optional[str] = None
    if outfit.slots:
        try:
            collage_url = get_or_create_grid_collage(
                user_id, outfit.slots, no_persist=no_persist
            )
        except Exception as exc:  # noqa: BLE001 — collage must never break the look
            logger.warning(
                "todays_look collage failed: %s (user=%s)",
                type(exc).__name__, user_id,
            )

    caption = _caption(
        factors.occasion, factors.warmth, factors.wet, composed.below_ideal
    )
    if extra_note and not starter:
        caption = f"{caption}  {extra_note}".strip()

    # Note: starter -> the add-pieces prompt; a based look missing only shoes -> the
    # completing nudge (folded into the caption, mirroring extra_note); otherwise none.
    note: Optional[str] = None
    if starter:
        note = _STARTER_NOTE
    elif based and "footwear" not in outfit.slots:
        note = _SHOE_NUDGE
        caption = f"{caption}  {note}".strip()

    return TodaysLook(
        kind=kind,
        outfit=outfit,
        items=items,
        item_ids=item_ids,
        collage_url=collage_url,
        title=_title(items),
        caption=caption,
        occasion=factors.occasion,
        warmth=factors.warmth,
        formality=composed.used_formality,
        note=note,
    )


def compose_todays_look(
    db: Session,
    user_id: UUID,
    *,
    factors: Optional[Factors] = None,
    exclude_item_ids: Optional[List[UUID]] = None,
    no_persist: bool = False,
) -> TodaysLook:
    """Compose the day's look (deterministic). See module docstring for the spine.

    ``factors`` may be passed by the route (it derives them for the cache signature)
    to avoid a second weather/calendar read; otherwise they're derived here.
    ``no_persist`` skips the collage upload (no per-user storage trace).
    """
    profile = assemble_profile(db, user_id)
    if factors is None:
        factors = derive_factors(db, user_id, profile, no_persist=no_persist)

    owned = _load_owned(db, user_id)
    composed = _compose_best(
        db, user_id, profile,
        warmth=factors.warmth,
        occasion=factors.occasion,
        derived_formality=factors.formality_target,
        request_exclude=set(exclude_item_ids or []),
        owned=owned,
    )
    return _finalize(user_id, composed, factors, no_persist)


# Slot swap priority for Remix: vary the most-swappable slot first, and keep sole
# footwear/bottom until last (dropping them would break completeness).
_SWAP_PRIORITY = {
    "accessory": 0, "outerwear": 1, "top": 2, "dress": 3, "bottom": 4, "footwear": 5,
}
_REMIX_NO_VARIETY_NOTE = "That's the best full look for today."


def compose_remix(
    db: Session,
    user_id: UUID,
    *,
    current_item_ids: List[UUID],
    factors: Optional[Factors] = None,
    no_persist: bool = False,
) -> TodaysLook:
    """A DIFFERENT COMPLETE look — never a worse one.

    Runs the SAME ``_compose_best`` pipeline GET uses (formality step-down,
    owned-photo preference, undergarment/non-primary exclusion, completeness-first),
    but varies via MINIMAL swaps instead of excluding the whole current outfit:
    try excluding one current item at a time (most-swappable slot first); accept the
    first result that is COMPLETE and differs from the current set. A sole
    footwear/bottom is never dropped — excluding it just yields an incomplete
    candidate that's skipped. If no different complete look exists, return the
    current complete look unchanged (with a gentle note) — never a starter.
    """
    profile = assemble_profile(db, user_id)
    if factors is None:
        factors = derive_factors(db, user_id, profile, no_persist=no_persist)
    owned = _load_owned(db, user_id)
    by_id = {it.id: it for it in owned}
    # Ownership filter: only the caller's own current items steer the swap.
    current = [by_id[i] for i in (current_item_ids or []) if i in by_id]
    current_set = {str(i.id) for i in current}

    def _best(exclude: Set[UUID]) -> _Composed:
        return _compose_best(
            db, user_id, profile,
            warmth=factors.warmth, occasion=factors.occasion,
            derived_formality=factors.formality_target,
            request_exclude=exclude, owned=owned,
        )

    # Single-slot swaps, most-swappable slot first.
    for item in sorted(current, key=lambda it: _SWAP_PRIORITY.get(_slot_of(it) or "", 9)):
        composed = _best({item.id})
        outfit = composed.outfit
        if outfit.slots and not outfit.gaps:
            new_set = {str(x.id) for x in outfit.slots.values()}
            if new_set != current_set:
                return _finalize(user_id, composed, factors, no_persist)

    # No different complete look reachable — keep the current complete look.
    composed = _best(set())
    complete = bool(composed.outfit.slots) and not composed.outfit.gaps
    note = _REMIX_NO_VARIETY_NOTE if (complete and current_set) else None
    return _finalize(user_id, composed, factors, no_persist, extra_note=note)
