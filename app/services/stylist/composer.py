"""compose_outfit: deterministic, slot-based outfit composition over OWNED items.

The MODEL never assembles outfits from thin air — it calls this tool, which runs
entirely server-side over the caller's closet and returns items + a stored
rationale. Determinism matters: same closet + same request = same outfit, so
tests can assert the rules and users get stable behavior.

SLOTS: separates (top + bottom + footwear [+ outerwear] [+ accessory]) or a
dress base (dress + footwear [+ outerwear] [+ accessory]) — the dress route is
taken when it outscores the separates route.

RULES (in order of authority):
  1. HARD profile constraints (facts avoid-lists) — matching items are EXCLUDED
     from the pool outright, never merely penalized.
  2. Formality band — an item with known formality must sit within ±1 of the
     target (locked rule). Unknown formality is allowed with a small penalty.
  3. Warmth/weather — warmth_target 1..3 filters obviously-wrong items (±1 band,
     unknown tolerated) and decides whether the outerwear slot is filled.
  4. Occasion — items whose occasions[] contain the request score up; never a
     hard block (enrichment coverage is sparse).
  5. Color harmony — neutrals always pass; otherwise hue-family scoring from
     color_primary_hex (falls back to color-name buckets).
  6. Preference weights — active style_preferences nudge scores (like/dislike),
     favorites get a small boost; recently-worn items are rotated down.

Anchors: validated-owned item ids that MUST appear; their slots are locked and
the rest of the outfit is scored around them (harmony against anchors doubled).
"""
from __future__ import annotations

import colorsys
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import ClothingItem
from app.services.enrichment import normalize_category
from app.services.stylist.profile import ProfileBlock
from app.services.stylist.retrieval import get_owned_items, search_closet_items, serialize_item

logger = logging.getLogger(__name__)

SLOT_CATEGORIES: Dict[str, Tuple[str, ...]] = {
    "top": ("top",),
    "bottom": ("bottom",),
    "dress": ("dress",),
    "footwear": ("footwear", "shoes"),
    "outerwear": ("outerwear", "suiting"),
    "accessory": ("accessory", "accessories", "bag"),
}

_NEUTRALS = frozenset(
    {"black", "white", "grey", "gray", "charcoal", "navy", "beige", "cream",
     "tan", "khaki", "ivory", "off-white", "offwhite", "denim", "brown", "stone"}
)

# Fields a hard avoid-token is matched against (word-level, case-insensitive).
_AVOID_FIELDS = ("category", "sub_category", "color_primary", "material", "pattern", "name")

# --- Occasion FAMILIES with hard composition rules --------------------------
# Most occasions are soft-scored (a tag nudges an item up, nothing is blocked).
# A FAMILY, by contrast, carries a category/attribute requirement the outfit
# MUST satisfy — so a gym request is filled only with activewear, never with
# whatever happens to be closest. Requests outside a family keep soft scoring.
_ATHLETIC_OCCASIONS = frozenset({
    "gym", "workout", "work out", "working out", "training", "train", "exercise",
    "run", "running", "jog", "jogging", "yoga", "pilates", "crossfit", "hiit",
    "cycling", "spin", "spinning", "sport", "sports", "athletic", "lifting",
    "weightlifting", "cardio", "tennis", "basketball", "soccer",
})
# Signals that an item is activewear / athletic-appropriate (matched against the
# item's descriptive fields + its occasion tags).
_ATHLETIC_TOKENS = frozenset({
    "athletic", "activewear", "active", "sport", "sports", "gym", "training",
    "workout", "performance", "running", "run", "track", "jogger", "joggers",
    "sweatpant", "sweatpants", "sweatshirt", "hoodie", "legging", "leggings",
    "tights", "tank", "jersey", "compression", "yoga", "spandex", "lycra",
    "polyester", "dri-fit", "drifit", "trainer", "trainers", "sneaker",
    "sneakers", "cleat", "cleats", "gymwear",
})
# Footwear that is decisively NOT gym-appropriate, even if some other token on
# the item (a brand, a colour) happened to look athletic.
_NONATHLETIC_FOOTWEAR_TOKENS = frozenset({
    "flat", "flats", "heel", "heels", "pump", "pumps", "loafer", "loafers",
    "oxford", "oxfords", "brogue", "brogues", "derby", "boot", "boots",
    "sandal", "sandals", "mule", "mules", "espadrille", "espadrilles",
    "wingtip", "clog", "clogs", "slipper", "slippers", "moccasin", "boat",
})

# Below this, an outfit is not presented as a confident recommendation.
_CONFIDENCE_FLOOR = 0.6


def occasion_family(occasion: Optional[str]) -> Optional[str]:
    """Map a free-text occasion to a family with HARD composition rules, or None
    for the default soft-scored behaviour. Extend here as new families earn
    dedicated rules (formal/black-tie is the obvious next one)."""
    if not occasion:
        return None
    low = str(occasion).lower()
    # WORD-level match, not substring: "brunch" must not trip on "run".
    # Multi-word terms ("work out") still match as phrases.
    toks = set(_tokens(low))
    if toks & _ATHLETIC_OCCASIONS:
        return "athletic"
    if any(" " in term and term in low for term in _ATHLETIC_OCCASIONS):
        return "athletic"
    return None


def _descriptive_tokens(item: ClothingItem) -> set:
    """All word-level tokens from an item's descriptive fields + occasion tags."""
    toks: set = set()
    for field_name in _AVOID_FIELDS:
        toks.update(_tokens(getattr(item, field_name, None)))
    for occ in (getattr(item, "occasions", None) or []):
        toks.update(_tokens(str(occ)))
    return toks


def _is_athletic_item(item: ClothingItem, slot: Optional[str]) -> bool:
    """Activewear check: the item must carry an athletic signal, and a footwear
    item additionally must not be an obviously non-athletic shoe (flats, heels,
    loafers, boots…). This is what rejects 'flats + jeans + a baseball cap' from
    a gym request rather than jamming them in."""
    toks = _descriptive_tokens(item)
    if slot == "footwear" and (toks & _NONATHLETIC_FOOTWEAR_TOKENS):
        return False
    return bool(toks & _ATHLETIC_TOKENS)


def _occasion_family_allows(item: ClothingItem, slot: Optional[str], family: Optional[str]) -> bool:
    """Hard occasion-family gate applied while building the candidate pool. None
    family = allow everything (unchanged soft-scoring path)."""
    if family is None:
        return True
    if family == "athletic":
        return _is_athletic_item(item, slot)
    return True


@dataclass
class ComposedOutfit:
    slots: Dict[str, ClothingItem] = field(default_factory=dict)
    score: float = 0.0
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    # Quality signal (set by compose_outfit). ``sufficient`` is False when a
    # REQUIRED slot could not be filled with an appropriate item — the closet
    # genuinely lacks the pieces for this request, and the agent must say so
    # instead of presenting a forced outfit. ``gaps`` names the missing slots.
    sufficient: bool = True
    confidence: float = 1.0
    gaps: List[str] = field(default_factory=list)

    def to_payload(self) -> Dict[str, Any]:
        return {
            "slots": {slot: serialize_item(item) for slot, item in self.slots.items()},
            "itemIds": [str(item.id) for item in self.slots.values()],
            "rationale": self.rationale,
            "warnings": self.warnings,
            # Honesty signal the model MUST respect (see the stylist persona's
            # grounding rules): never dress up a low-confidence result as good.
            "sufficient": self.sufficient,
            "confidence": round(self.confidence, 2),
            "gaps": list(self.gaps),
        }

    @property
    def rationale(self) -> str:
        return " ".join(self.reasons) if self.reasons else ""


def _tokens(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [t for t in str(value).lower().replace("_", " ").split() if t]


def violates_hard_constraints(item: ClothingItem, hard_avoids: Sequence[str]) -> bool:
    """True when any avoid-token matches any of the item's descriptive fields.

    Word-level matching ('skirts' matches 'skirt_mini' via token overlap after
    normalization; 'red' matches color 'red' but not 'bordeaux'). Conservative
    and literal — hard constraints are user law, so false-positive exclusion is
    preferred over a violation.
    """
    if not hard_avoids:
        return False
    item_tokens: set[str] = set()
    for field_name in _AVOID_FIELDS:
        item_tokens.update(_tokens(getattr(item, field_name, None)))
    for avoid in hard_avoids:
        avoid_tokens = _tokens(avoid)
        if not avoid_tokens:
            continue
        # singular/plural-tolerant containment: every avoid token must appear
        # (allowing a trailing-'s' mismatch either way).
        if all(
            any(t == a or t == a.rstrip("s") or a == t.rstrip("s") for t in item_tokens)
            for a in avoid_tokens
        ):
            return True
    return False


def _formality_ok(item: ClothingItem, target: Optional[int]) -> bool:
    """Locked rule: known formality must be within ±1 of the target."""
    if target is None or item.formality is None:
        return True
    return abs(int(item.formality) - int(target)) <= 1


def _warmth_ok(item: ClothingItem, target: Optional[int]) -> bool:
    if target is None or item.warmth is None:
        return True
    return abs(int(item.warmth) - int(target)) <= 1


def _hue(hex_color: Optional[str]) -> Optional[float]:
    if not hex_color:
        return None
    value = hex_color.lstrip("#")
    if len(value) != 6:
        return None
    try:
        r, g, b = (int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return None
    h, _l, s = colorsys.rgb_to_hls(r, g, b)
    if s < 0.15:  # desaturated = effectively neutral
        return None
    return h * 360.0


def _is_neutral(item: ClothingItem) -> bool:
    color = (item.color_primary or "").strip().lower()
    if color in _NEUTRALS:
        return True
    return _hue(item.color_primary_hex) is None and bool(color or item.color_primary_hex)


def color_harmony(a: ClothingItem, b: ClothingItem) -> float:
    """Pairwise harmony in [-1, 1]. Neutral pairs are safely harmonious; two
    saturated colors score by hue relationship (analogous/complementary good,
    awkward mid-distance clashes negative). Unknown colors are neutral-0."""
    if _is_neutral(a) or _is_neutral(b):
        return 0.5
    ha, hb = _hue(a.color_primary_hex), _hue(b.color_primary_hex)
    if ha is None or hb is None:
        return 0.0
    diff = abs(ha - hb)
    diff = min(diff, 360 - diff)
    if diff <= 40:      # same family / analogous
        return 0.8
    if diff >= 150:     # complementary-ish
        return 0.4
    if diff <= 75:      # adjacent — fine
        return 0.2
    return -0.6         # mid-distance clash


def _preference_score(item: ClothingItem, profile: ProfileBlock) -> Tuple[float, List[str]]:
    """Nudge from active style_preferences whose value tokens match the item."""
    score = 0.0
    notes: List[str] = []
    item_tokens: set[str] = set()
    for field_name in _AVOID_FIELDS:
        item_tokens.update(_tokens(getattr(item, field_name, None)))
    for pref in profile.preferences:
        pref_tokens = set(_tokens(str(pref.get("dimension", ""))))
        pref_tokens.update(_tokens(str(pref.get("value", ""))))
        if not (pref_tokens & item_tokens):
            continue
        confidence = pref.get("confidence") or 0.5
        if pref.get("polarity") == "like":
            score += 1.5 * confidence
            notes.append(f"matches your liked {pref['dimension']}")
        elif pref.get("polarity") == "dislike":
            score -= 3.0 * confidence
    return score, notes


def _item_score(
    item: ClothingItem,
    *,
    formality_target: Optional[int],
    warmth_target: Optional[int],
    occasion: Optional[str],
    profile: ProfileBlock,
) -> Tuple[float, List[str]]:
    score = 0.0
    notes: List[str] = []

    if formality_target is not None:
        if item.formality is None:
            score -= 0.3  # unknown: allowed, slightly less trusted
        else:
            score += 1.0 - 0.5 * abs(int(item.formality) - int(formality_target))
    if warmth_target is not None and item.warmth is not None:
        score += 0.5 - 0.5 * abs(int(item.warmth) - int(warmth_target))
    if occasion and item.occasions:
        if occasion.lower() in [str(o).lower() for o in item.occasions]:
            score += 2.0
            notes.append(f"tagged for {occasion}")
    pref_score, pref_notes = _preference_score(item, profile)
    score += pref_score
    notes.extend(pref_notes[:1])
    if item.is_favorite:
        score += 0.5
        notes.append("one of your favorites")
    if item.last_worn_at is not None:
        try:
            if item.last_worn_at.replace(tzinfo=None) > datetime.utcnow() - timedelta(days=3):
                score -= 0.5  # rotate: worn in the last few days
        except (TypeError, ValueError):
            pass
    return score, notes


def _candidate_pool(
    db: Session,
    user_id: UUID,
    *,
    formality_target: Optional[int],
    warmth_target: Optional[int],
    occasion: Optional[str],
    season: Optional[str],
    profile: ProfileBlock,
    exclude_ids: set[UUID],
    family: Optional[str] = None,
) -> Dict[str, List[ClothingItem]]:
    """Per-slot candidates, already hard-filtered (constraints/formality/warmth,
    and — for an occasion FAMILY like athletic — appropriateness)."""
    band = (
        (max(1, formality_target - 1), min(5, formality_target + 1))
        if formality_target is not None
        else (None, None)
    )
    pool: Dict[str, List[ClothingItem]] = {}
    for slot, cats in SLOT_CATEGORIES.items():
        items = search_closet_items(
            db,
            user_id,
            categories=list(cats),
            formality_min=band[0],
            formality_max=band[1],
            season=season,
            occasion=None,  # occasion is a soft score, not a filter (sparse data)
            limit=None,
        )
        pool[slot] = [
            it
            for it in items
            if it.id not in exclude_ids
            and not violates_hard_constraints(it, profile.hard_avoids)
            and _formality_ok(it, formality_target)
            and _warmth_ok(it, warmth_target)
            and _occasion_family_allows(it, slot, family)
        ]
    return pool


def _slot_of(item: ClothingItem) -> Optional[str]:
    category = normalize_category(item.category) or (item.category or "")
    for slot, cats in SLOT_CATEGORIES.items():
        if category in cats:
            return slot
    return None


def _pick(
    candidates: List[ClothingItem],
    chosen: Dict[str, ClothingItem],
    anchor_ids: set[UUID],
    score_kwargs: Dict[str, Any],
) -> Optional[Tuple[ClothingItem, float, List[str]]]:
    """Best candidate for a slot: base score + harmony with already-chosen items
    (doubled against anchors). Deterministic tie-break on item id."""
    best: Optional[Tuple[ClothingItem, float, List[str]]] = None
    for item in candidates:
        score, notes = _item_score(item, **score_kwargs)
        for other in chosen.values():
            harmony = color_harmony(item, other)
            score += harmony * (2.0 if other.id in anchor_ids else 1.0)
        if best is None or (score, str(item.id)) > (best[1], str(best[0].id)):
            best = (item, score, notes)
    return best


def compose_outfit(
    db: Session,
    user_id: UUID,
    profile: ProfileBlock,
    *,
    occasion: Optional[str] = None,
    formality_target: Optional[int] = None,
    warmth_target: Optional[int] = None,
    season: Optional[str] = None,
    anchor_item_ids: Optional[List[UUID]] = None,
    exclude_item_ids: Optional[List[UUID]] = None,
) -> ComposedOutfit:
    """Compose one outfit from the caller's closet under the rules above.

    Anchors are resolved through :func:`get_owned_items` — a foreign or unknown
    id simply doesn't resolve, and the tool layer reports it, so a coerced id
    can never pull another user's item into an outfit.
    """
    if formality_target is not None:
        formality_target = max(1, min(5, int(formality_target)))
    if warmth_target is not None:
        warmth_target = max(1, min(3, int(warmth_target)))

    family = occasion_family(occasion)
    exclude_ids = set(exclude_item_ids or [])
    outfit = ComposedOutfit()
    anchor_ids: set[UUID] = set()

    anchors = get_owned_items(db, user_id, anchor_item_ids or [])
    for anchor in anchors:
        if violates_hard_constraints(anchor, profile.hard_avoids):
            outfit.warnings.append(
                f"'{anchor.name}' conflicts with your hard constraints; left it out."
            )
            continue
        slot = _slot_of(anchor)
        if slot is None or slot in outfit.slots:
            outfit.warnings.append(f"couldn't place '{anchor.name}' in a slot")
            continue
        outfit.slots[slot] = anchor
        anchor_ids.add(anchor.id)

    score_kwargs = dict(
        formality_target=formality_target,
        warmth_target=warmth_target,
        occasion=occasion,
        profile=profile,
    )
    pool = _candidate_pool(
        db,
        user_id,
        formality_target=formality_target,
        warmth_target=warmth_target,
        occasion=occasion,
        season=season,
        profile=profile,
        exclude_ids=exclude_ids | anchor_ids,
        family=family,
    )

    # Base: dress vs separates. A dress anchor forces the dress route; a top or
    # bottom anchor forces separates; otherwise compare best-candidate scores.
    use_dress = "dress" in outfit.slots
    if not use_dress and not ({"top", "bottom"} & set(outfit.slots)):
        dress_best = _pick(pool["dress"], outfit.slots, anchor_ids, score_kwargs)
        top_best = _pick(pool["top"], outfit.slots, anchor_ids, score_kwargs)
        bottom_best = _pick(pool["bottom"], outfit.slots, anchor_ids, score_kwargs)
        separates_score = (
            (top_best[1] if top_best else -99) + (bottom_best[1] if bottom_best else -99)
        )
        use_dress = dress_best is not None and (
            separates_score < -50 or dress_best[1] * 2 > separates_score
        )

    base_slots = ["dress"] if use_dress else ["top", "bottom"]
    fill_order = base_slots + ["footwear"]
    # Outerwear only when it's cold enough or the look is formal.
    if (warmth_target or 0) >= 2 or (formality_target or 0) >= 4:
        fill_order.append("outerwear")
    fill_order.append("accessory")

    # Which slots this request REQUIRES (accessory/outerwear are optional).
    required_slots = [s for s in fill_order if s in (base_slots + ["footwear"])]

    for slot in fill_order:
        if slot in outfit.slots:
            continue
        picked = _pick(pool.get(slot, []), outfit.slots, anchor_ids, score_kwargs)
        if picked is None:
            if slot in ("top", "bottom", "dress", "footwear"):
                # Name the occasion in the gap so the agent can be specific: an
                # empty athletic pool means "no gym-appropriate X", not just "no X".
                qualifier = f"{occasion}-appropriate " if (occasion and family) else ""
                outfit.warnings.append(
                    f"no {qualifier}owned {slot} in your closet — a gap worth shopping for"
                )
            continue
        item, score, notes = picked
        outfit.slots[slot] = item
        outfit.score += score
        detail = f" ({notes[0]})" if notes else ""
        outfit.reasons.append(f"{item.name} as the {slot}{detail}.")

    # --- Quality signal: did we actually build something appropriate? ---------
    # A required slot left unfilled means the closet lacks a suitable piece — the
    # outfit is NOT sufficient and the agent must be honest about the gap rather
    # than present a partial/forced look as finished.
    unfilled_required = [s for s in required_slots if s not in outfit.slots]
    outfit.gaps = unfilled_required
    filled_required = [s for s in required_slots if s in outfit.slots]
    coverage = len(filled_required) / len(required_slots) if required_slots else 1.0

    if occasion and filled_required:
        # How many filled required slots actually SUIT the occasion (family-gated
        # picks are appropriate by construction; otherwise credit an occasion tag).
        occ_low = occasion.lower()
        supportive = 0
        for s in filled_required:
            it = outfit.slots[s]
            tagged = it.occasions and occ_low in [str(o).lower() for o in it.occasions]
            if family is not None or tagged:
                supportive += 1
        occasion_fit = supportive / len(filled_required)
        outfit.confidence = coverage * (0.55 + 0.45 * occasion_fit)
    else:
        outfit.confidence = coverage

    outfit.sufficient = not unfilled_required and outfit.confidence >= _CONFIDENCE_FLOOR

    if occasion:
        outfit.reasons.insert(0, f"Built for {occasion}.")
    if formality_target is not None:
        outfit.reasons.append(
            f"Everything sits within one step of formality {formality_target}."
        )
    if not outfit.sufficient:
        gap_txt = ", ".join(unfilled_required) if unfilled_required else "a good match"
        qualifier = f"{occasion}-appropriate " if (occasion and family) else ""
        outfit.reasons.append(
            f"Heads up: your closet is missing {qualifier}{gap_txt} — this is a "
            "partial idea, not a finished outfit."
        )
    return outfit
