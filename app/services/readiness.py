"""THE shared ready-first candidate state machine — one definition, both pipelines.

Photo-seam Phase 1: the pipeline_state / person_status machine introduced by the Gmail
ready-first work (Phases 1-3) is the app-wide readiness truth, so its definition moves to
this NEUTRAL services module and BOTH ingest pipelines import it downward:

  * app.gmail_closet.image_fill_service — the Gmail fill pass (staging → fill → settle)
  * app.photo_closet.generation_service — the photo cutout → product-card pass

Nothing here touches the DB or providers: pure state predicates + transition writers over
an IngestCandidate row. The caller owns the session/commit.

THE READY INVARIANT (single writer: mark_candidate_ready)
----------------------------------------------------------
ready ⟺ an AFFIRMATIVE person_free verdict
        AND a stored, VERIFIED, displayable product image (has_verified_card)
        AND complete tags (name + category mandatory, size present-or-sizeless)

`has_verified_card` is source-aware because the two pipelines store the card in different
columns (a photo candidate keeps its raw cutout in image_url and the verified card in
generated_image_url; a Gmail candidate's verified image IS image_url):

  * photo  → generated_image_url present AND generation_status == 'ready'
             (the generation pass writes those ONLY after the mandatory pair-verify,
              which hard-fails person_present)
  * gmail  → image_url present AND image_status in STORED_IMAGE_STATUSES
             (written only by the resolver/fill after its verify/person gates)

A photo candidate's raw cutout alone NEVER satisfies the invariant — the source_type
branch exists precisely so image_url='the crop' + image_status='user_uploaded' cannot
masquerade as a verified card.
"""
from __future__ import annotations

from typing import Optional

from app.services.closet_canonicalize import (
    _CATEGORY_SIZE_KEY,
    default_size_for_category,
)

# Forward-only ordering of the non-terminal pipeline states. `advance` never regresses
# a candidate and never leaves a terminal ('ready'/'failed' are written only by
# mark_candidate_ready / the pipelines' terminal stampers).
STATE_ORDER = {
    "staged": 0, "canonicalized": 1, "image_pending": 2,
    "image_generated": 3, "verified_clean": 4,
}
TERMINAL_STATES = ("ready", "failed")
# image_status values that count as a stored, displayable image for readiness (gmail shape).
STORED_IMAGE_STATUSES = ("resolved", "user_uploaded")


def advance(cand, state: str) -> None:
    """Move the candidate FORWARD to ``state``; never regress, never leave a terminal."""
    if cand.pipeline_state in TERMINAL_STATES:
        return
    if STATE_ORDER.get(state, -1) > STATE_ORDER.get(cand.pipeline_state, -1):
        cand.pipeline_state = state


def size_ok(category: Optional[str], size: Optional[str]) -> bool:
    """Size readiness: present, or the category has no size concept (no default key)."""
    if size:
        return True
    return (category or "").strip().lower() not in _CATEGORY_SIZE_KEY


def tags_ready(cand) -> bool:
    """Gate-3 tag completeness: category + name mandatory, size present-or-sizeless."""
    return bool((cand.name or "").strip()) and bool((cand.category or "").strip()) and size_ok(
        cand.category, cand.size
    )


def apply_canonicalized(cand, facts: Optional[dict]) -> None:
    """Stage-time canonicalize-lite: default a missing size from the user's onboarding
    sizes (facts.sizes, same lookup confirm uses), then advance to 'canonicalized'."""
    if cand.pipeline_state in TERMINAL_STATES:
        return
    if not cand.size:
        default = default_size_for_category((facts or {}).get("sizes"), cand.category)
        if default:
            cand.size = default
    advance(cand, "canonicalized")


def has_verified_card(cand) -> bool:
    """True when the candidate holds a stored, VERIFIED, displayable product image.

    Source-aware (see module docstring): the photo card lives in generated_image_url;
    the gmail verified image IS image_url. A photo candidate's raw cutout never counts.
    """
    if (getattr(cand, "source_type", None) or "") == "photo":
        return bool(cand.generated_image_url) and cand.generation_status == "ready"
    return bool(cand.image_url) and (cand.image_status or "") in STORED_IMAGE_STATUSES


def needs_size(cand) -> bool:
    """True when a candidate is held at 'verified_clean' ONLY by a missing size.

    Photo-seam Phase 3: these candidates have a verified, person-free, invariant-
    compliant card and complete name/category — the one thing the pipeline cannot
    supply is a size (no onboarding default for the category). They SURFACE in the
    review deck with a needs-size affordance and count as settled-but-actionable in
    the whole-batch settle — never silently stuck, never blocking the batch forever."""
    return (
        cand.pipeline_state == "verified_clean"
        and cand.person_status == "person_free"
        and has_verified_card(cand)
        and bool((cand.name or "").strip())
        and bool((cand.category or "").strip())
        and not size_ok(cand.category, cand.size)
    )


def mark_candidate_ready(cand) -> None:
    """THE single writer of pipeline_state='ready' — for BOTH pipelines.

    Enforces the ready invariant in code: ready ⟺ an AFFIRMATIVE person_free verdict
    AND a stored, verified image AND complete tags. Anything else is a bug — raise so
    the (already fail-safe) caller surfaces it instead of leaking an unready card."""
    if (
        cand.person_status != "person_free"
        or not has_verified_card(cand)
        or not tags_ready(cand)
    ):
        raise AssertionError(
            "ready invariant violated: source=%s person=%s card=%s image_status=%s gen=%s"
            % (
                getattr(cand, "source_type", None), cand.person_status,
                has_verified_card(cand), cand.image_status, cand.generation_status,
            )
        )
    cand.pipeline_state = "ready"
