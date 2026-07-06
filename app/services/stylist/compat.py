"""Pure, DB-free compatibility surface for batch jobs (F1a).

The outfit composer's compatibility logic is entirely deterministic — no LLM, no
network, no DB — a set of predicates over typed ``ClothingItem`` attributes plus
the greedy slot assembler. This module is the stable import point for offline
consumers (the nightly wardrobe-gap / marginal-outfit-unlock job) so they never
reach into ``composer`` internals or accidentally pull in the DB-bound shell.

Everything here operates on in-memory objects only. ``assemble_from_pool`` is the
same code path ``compose_outfit`` runs after its DB loads, so a candidate scored
here is scored by the identical rules the chat stylist uses.

    from app.services.stylist.compat import assemble_from_pool, color_harmony

Nothing in this module imports a Session or an AI provider; keep it that way so
the batch contract (no DB, no LLM) is enforced by construction.
"""
from __future__ import annotations

from app.services.stylist.composer import (
    SLOT_CATEGORIES,
    ComposedOutfit,
    assemble_from_pool,
    color_harmony,
    occasion_family,
    violates_hard_constraints,
    _formality_ok,
    _item_score,
    _occasion_family_allows,
    _warmth_ok,
)

# Public aliases for the underscore-private predicates so batch callers import a
# clean name and never depend on composer's private spelling.
formality_ok = _formality_ok
warmth_ok = _warmth_ok
occasion_family_allows = _occasion_family_allows
item_score = _item_score

__all__ = [
    "assemble_from_pool",
    "ComposedOutfit",
    "SLOT_CATEGORIES",
    "violates_hard_constraints",
    "color_harmony",
    "occasion_family",
    "formality_ok",
    "warmth_ok",
    "occasion_family_allows",
    "item_score",
    # underscore originals, re-exported for parity with composer
    "_formality_ok",
    "_warmth_ok",
    "_occasion_family_allows",
    "_item_score",
]
