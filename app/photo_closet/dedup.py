"""Closet dedup seam (Wave 1 STUB).

A staged photo garment may already exist in the user's closet (bought via a Gmail
receipt, or uploaded in an earlier photo). The real matching logic — visual / attribute
similarity against existing clothing_items — is a SEPARATE session. This module is the
seam it will fill: the photo pipeline already calls ``dedup_check`` for every staged
candidate, so the later matcher (and the generation gate that hangs off it) drops in
with no pipeline change.

For now it always returns ``unique`` — nothing is gated.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

DedupVerdict = Literal["unique", "duplicate", "uncertain"]


@dataclass(frozen=True)
class DedupResult:
    verdict: DedupVerdict
    # The clothing_items.id a real matcher matched against (None for the stub).
    matched_item_id: str | None = None
    score: float = 0.0
    reason: str = "stub: matching not implemented"


def dedup_check(db, user_id: UUID, candidate) -> DedupResult:
    """Return whether ``candidate`` duplicates something already in the user's closet.

    STUB: always 'unique'. Signature is stable so the real matcher (and any
    generation gating behind it) can replace the body without touching callers.
    ``candidate`` is an IngestCandidate (staged, not yet confirmed).
    """
    return DedupResult(verdict="unique")
