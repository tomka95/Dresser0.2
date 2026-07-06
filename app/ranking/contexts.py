"""The wardrobe-context grid: occasion × formality × warmth over the IL climate calendar.

A fixed, interpretable list of the situations a wardrobe must cover across an Illinois
year — cold winters (warmth 3), mild spring/fall (warmth 2), hot summers (warmth 1) crossed
with the everyday occasion set. The wardrobe-gap job asks, per candidate product: "how many
of these contexts does owning it newly let you dress for?" (see app.ranking.gap).

Kept small and explicit (not a full cross-product) so the marginal-unlock combinatorics stay
cheap and every context is a real, nameable occasion rather than an empty cell.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class WardrobeContext:
    label: str
    occasion: Optional[str]
    formality: int          # 1..5
    warmth: int             # 1..3 (season proxy: 3=winter, 2=spring/fall, 1=summer)
    l1: bool = False        # an L1 occasion: zero closet coverage of it is a real gap


# IL calendar × occasion. l1=True marks the load-bearing everyday contexts whose
# zero-coverage earns the ranker's occasion-gap bonus.
CONTEXT_GRID: List[WardrobeContext] = [
    WardrobeContext("work_winter", "work", 3, 3, l1=True),
    WardrobeContext("work_summer", "work", 3, 1, l1=True),
    WardrobeContext("casual_winter", "casual", 2, 3, l1=True),
    WardrobeContext("casual_summer", "casual", 1, 1, l1=True),
    WardrobeContext("weekend_layers", "casual", 2, 2),
    WardrobeContext("date_night", "date", 3, 2, l1=True),
    WardrobeContext("evening_out", "evening", 4, 2, l1=True),
    WardrobeContext("formal_event", "formal", 5, 2),
    WardrobeContext("brunch", "brunch", 2, 2),
    WardrobeContext("gym", "gym", 1, 1, l1=True),
    WardrobeContext("interview", "work", 4, 2),
    WardrobeContext("summer_evening", "evening", 3, 1),
]
