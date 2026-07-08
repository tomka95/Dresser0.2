"""Today's Look — one auto-composed outfit for the day, shown on Home open.

This is the deterministic spine behind ``GET /todays-look`` and its ``/remix``
sibling. It mirrors the stylist ``compose_outfit`` tool (tools.py:_tool_compose_outfit)
but with NO model in the loop at any point:

  * weather  -> ``forecast_for_facts`` gives a warmth band (1 hot..3 cold) that
    feeds the composer's ``warmth_target`` — exactly the tool's path;
  * calendar -> ``assemble_calendar`` derives an OCCASION + FORMALITY server-side.
    Only the derived occasion/formality cross into here; raw event titles are
    NEVER read or persisted by this module;
  * profile  -> ``assemble_profile`` (hard avoids, preferences) as always;
  * compose  -> the pure, rule-based ``compose_outfit`` (same closet + same day =
    same outfit);
  * collage  -> ``get_or_create_grid_collage``: every item knocked out on ONE
    pure-white field, side by side (pure PIL, no image API).

The caption is a deterministic template (occasion phrase + a weather-aware layer
line) — no model call, no free text from anywhere untrusted.

FAILURE POSTURE: weather, calendar and collage are each best-effort. Any of them
failing degrades the look (no warmth line / no occasion / no collage image) but
NEVER raises — Home must not 500 on a flaky provider. A closet too thin to fill
the required slots yields a ``starter`` look (whatever we could place + a note),
never an error.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.services.stylist.calendar import CalendarBlock, assemble_calendar
from app.services.stylist.collage import get_or_create_grid_collage, usable_image_url
from app.services.stylist.composer import ComposedOutfit, compose_outfit
from app.services.stylist.profile import assemble_profile
from app.services.stylist.retrieval import serialize_item

try:  # weather is optional infra; import must never hard-fail the module
    from app.services.weather.service import forecast_for_facts
except Exception:  # pragma: no cover - defensive
    forecast_for_facts = None  # type: ignore

logger = logging.getLogger(__name__)

# Cell order in the title/collage: silhouette first, then finishing pieces.
_SLOT_ORDER = ("outerwear", "top", "dress", "bottom", "footwear", "accessory")


# ---------------------------------------------------------------------------
# Deterministic caption (occasion phrase + weather-aware layer line). No model.
# ---------------------------------------------------------------------------
# occasion -> lead phrase. Keys are the exact strings derive_dress_context emits.
_OCCASION_LEAD = {
    "a formal event": "Dressed to the nines.",
    "an interview": "Interview-ready.",
    "work": "Meeting-sharp.",
    "dinner out": "Dinner-ready.",
    "something casual": "Easy and off-duty.",
    "the gym": "Ready to move.",
}
_DEFAULT_LEAD = "Put-together for whatever today holds."

# warmth band (1 hot..3 cold) -> dry-day layer line.
_WARMTH_LAYER = {
    1: "Skip the layers.",
    2: "Coat optional.",
    3: "Layer up — it's cold out.",
}


def _caption(occasion: Optional[str], warmth: Optional[int], wet: bool) -> str:
    """Compose the two-clause caption deterministically."""
    lead = _OCCASION_LEAD.get(occasion or "", _DEFAULT_LEAD)
    if wet:
        layer = "Rain's likely — bring a shell."
    elif warmth in _WARMTH_LAYER:
        layer = _WARMTH_LAYER[warmth]
    else:
        layer = ""
    return f"{lead} {layer}".strip()


def _title(items: List[Dict[str, Any]]) -> str:
    """Item names joined ("Linen shirt, black jeans, chelseas")."""
    names = [str(it.get("name") or "").strip() for it in items]
    names = [n for n in names if n]
    return ", ".join(names)


def _ordered_items(outfit: ComposedOutfit) -> List[tuple]:
    order = {s: i for i, s in enumerate(_SLOT_ORDER)}
    return sorted(outfit.slots.items(), key=lambda kv: order.get(kv[0], 99))


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------
@dataclass
class TodaysLook:
    kind: str  # "look" (complete) | "starter" (thin closet / missing required slot)
    outfit: ComposedOutfit
    items: List[Dict[str, Any]] = field(default_factory=list)
    item_ids: List[str] = field(default_factory=list)
    collage_url: Optional[str] = None
    title: str = ""
    caption: str = ""
    occasion: Optional[str] = None
    warmth: Optional[int] = None
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
            "note": self.note,
            "rationale": self.outfit.rationale,
        }


_STARTER_NOTE = (
    "Add a few more pieces and Tailor can build you a full look for the day."
)


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


def _read_calendar(db: Session, user_id: UUID, no_persist: bool) -> CalendarBlock:
    """Derived occasion/formality only. Best-effort — never raises."""
    try:
        return assemble_calendar(db, user_id, no_persist=no_persist)
    except Exception as exc:  # noqa: BLE001
        logger.warning("todays_look calendar read failed: %s", type(exc).__name__)
        return CalendarBlock()


def _item_payload(item) -> Dict[str, Any]:
    """serialize_item + an explicit hasImage flag (usable, showable photo)."""
    payload = serialize_item(item)
    payload["hasImage"] = usable_image_url(item) is not None
    return payload


def compose_todays_look(
    db: Session,
    user_id: UUID,
    *,
    exclude_item_ids: Optional[List[UUID]] = None,
    no_persist: bool = False,
) -> TodaysLook:
    """Compose the day's look (deterministic). See module docstring for the spine.

    ``exclude_item_ids`` drives the Remix path (exclude the current outfit so the
    composer surfaces an alternative). ``no_persist`` skips the collage upload
    (leaves no per-user storage trace).
    """
    profile = assemble_profile(db, user_id)

    warmth, wet, _forecast = _read_weather(profile.facts)
    cal = _read_calendar(db, user_id, no_persist)
    occasion = cal.occasion
    formality_target = cal.formality_target

    outfit = compose_outfit(
        db,
        user_id,
        profile,
        occasion=occasion,
        formality_target=formality_target,
        warmth_target=warmth,
        exclude_item_ids=exclude_item_ids,
    )

    ordered = _ordered_items(outfit)
    items = [_item_payload(it) for _slot, it in ordered]
    item_ids = [str(it.id) for _slot, it in ordered]

    # Thin closet / a required slot we couldn't fill -> starter look. We still
    # return whatever we placed (so the user sees their pieces), plus a note.
    starter = (not outfit.slots) or (not outfit.sufficient)
    kind = "starter" if starter else "look"

    # Collage: best-effort. A failure just leaves collageUrl None and the client
    # falls back to its own tile grid.
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

    return TodaysLook(
        kind=kind,
        outfit=outfit,
        items=items,
        item_ids=item_ids,
        collage_url=collage_url,
        title=_title(items),
        caption=_caption(occasion, warmth, wet),
        occasion=occasion,
        warmth=warmth,
        note=_STARTER_NOTE if starter else None,
    )
