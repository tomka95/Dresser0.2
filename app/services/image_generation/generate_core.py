"""Wave B (Fix 4) — the neutral, bytes-native generate→verify→store core.

WHY THIS LIVES HERE
-------------------
Two feature packages need to turn a reference image (or pure attributes) into a clean,
VERIFIED, person-free product image and store it:
  * app.photo_closet.generation_service — the photo cutout path (unchanged; keeps its own
    URL-based loop so its extensive monkeypatch-based tests keep intercepting).
  * app.gmail_closet.image_resolver — routes ON-MODEL email images (a person in frame)
    through generation, from raw bytes already in hand at resolve time.

Putting the shared core in the NEUTRAL app.services.image_generation layer (which imports
neither package back) lets both import it DOWNWARD, so the on-model routing does NOT create
a gmail_closet ↔ photo_closet import cycle (the cycle the P3.3 architecture note broke via
app.platform / a neutral layer). This module imports only the provider seam (same package),
the verify gate (app.gmail_closet.image_verify — an already-established services→gmail_closet
direction), storage (app.utils), and the t2i entry (lazy).

THE GUARANTEES (Fix 4)
----------------------
* MANDATORY verify: a candidate is returned ONLY when it passes the verify gate. For a
  reference-conditioned generation that is verify_generated_image (which now hard-FAILS on
  person_present — the structural "no person in the closet" backstop). For a text-to-image
  (no reference) it is verify_image PLUS an explicit person_present=false requirement.
* NEVER returns the on-model / reference original — only a freshly generated product image.
* Never raises; returns a held/budget outcome on any miss so callers fall through cleanly.

SECURITY/PRIVACY: providers receive garment bytes / attribute text only — never user
identity or order data. Steering text is fenced as untrusted (cannot force a person/scene/
logo past verify). Logs status/latency/ids only, never bytes or prompt text.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple
from uuid import UUID

from app.core.config import settings
from app.gmail_closet.image_verify import (
    VerifyBudget,
    verify_generated_image,
    verify_image,
)
from app.platform.usage import UsageAccumulator
from app.services.image_generation.base import (
    GenerationBudget,
    GenerationRequest,
    get_generation_provider,
    nano_fallback_enabled,
)
from app.services.image_generation.prompt import build_t2i_prompt  # noqa: F401 (re-export)

logger = logging.getLogger(__name__)

# Same live ladder as the photo path: FLUX.2 [pro] first (BFL, OFF the Gemini cap),
# nano_banana (Gemini, ON-cap) only as the verify-fail retry.
_LADDER: Tuple[str, ...] = ("flux2_pro", "nano_banana")
# TEXT->IMAGE ladder (imageless items: no crop, no reference). FLUX.2 [pro] t2i first
# (BFL, OFF the Gemini cap — runs regardless of the nano flag), nano_banana t2i (Gemini,
# ON-cap) only when the flag is on. The nano flag skips ONLY its own rung; it must never
# disable the off-cap FLUX.2 rung (that regression stranded 16 imageless Gmail items).
_T2I_LADDER: Tuple[str, ...] = ("flux2_t2i", "nano_banana")
_SUFFIX_BY_CT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


@dataclass
class GenOutcome:
    """Result of one generate→verify→store attempt (no image bytes / PII).

    outcome:
      ready           - verified + stored; url is the displayable card.
      verify_deferred - an off-cap image was generated + STORED but verify could not
                        run (429/error/disabled/budget). The url holds the stored
                        (unverified, must-stay-masked) image; a later self-heal
                        RE-VERIFIES it — no second generation charge. The ladder did
                        NOT advance to a more expensive rung.
      held            - a real generate→verify miss (content fail / storage down /
                        ladder exhausted).
      budget          - the per-run generation-call ceiling denied the first call.
    """
    outcome: str
    url: Optional[str] = None        # stored product-image URL (ready OR verify_deferred)
    content_sha256: Optional[str] = None
    verify_score: float = 0.0
    cost_usd: float = 0.0
    provider: Optional[str] = None   # which rung produced the image (observability)


def generation_armed() -> bool:
    """True when a ladder provider key AND the verify key (GEMINI_API_KEY) are present.

    Mirrors generation_service.generation_armed — callers use it to skip cleanly when
    generation isn't configured (dev without keys) rather than churn the ladder to no-ops.
    """
    from app.services.image_generation.base import list_available_providers

    available = list_available_providers()
    has_provider = any(available.get(name) for name in _LADDER)
    return has_provider and bool(settings.GEMINI_API_KEY)


def _store(storage_client, user_id: UUID, data: bytes, content_type: str) -> Optional[str]:
    """Persist verified generated bytes via content-addressed image_blobs dedup.

    Same folder as the photo generation path (generated_items/{user_id}); the dedup means
    identical bytes upload once. Returns the URL, or None if storage is unavailable."""
    if storage_client is None:
        return None
    from app.utils.image_blob_store import get_or_upload

    suffix = _SUFFIX_BY_CT.get(content_type, ".png")
    try:
        return get_or_upload(
            data,
            lambda: storage_client.upload_bytes(
                data,
                folder=f"generated_items/{user_id}",
                content_type=content_type,
                suffix=suffix,
            ),
        )
    except Exception as exc:
        logger.warning("generate_core: store failed (%s)", type(exc).__name__)
        return None


def generate_from_reference_bytes(
    *,
    reference_bytes: bytes,
    reference_content_type: str,
    name: Optional[str],
    category: Optional[str],
    color: Optional[str],
    brand: Optional[str],
    pattern: Optional[str] = None,
    storage_client,
    user_id: UUID,
    gen_budget: GenerationBudget,
    verify_budget: VerifyBudget,
    usage: UsageAccumulator,
    steering: Optional[str] = None,
    ladder: Optional[Sequence[str]] = None,
) -> GenOutcome:
    """Generate a clean product image CONDITIONED on reference bytes, verify, store.

    Bytes-native (no URL round-trip / no un-SSRF-guarded re-download): the caller passes
    the already-verified, SSRF-clean reference bytes it holds. Runs the provider ladder,
    gates EACH candidate on the MANDATORY verify_generated_image (which fails on any person
    in the candidate), stores the first pass. NEVER stores the reference itself. No DB
    writes — the caller persists the returned URL. Never raises.

    BUDGET COUNTS CALLS (cost cut #3): gen_budget.take() is consumed once per ACTUAL
    provider generation call (inside the rung loop), not once per candidate — so a ladder
    that walks N rungs costs N budget units and the per-run ceiling is a real cap on
    generation calls. Budget exhausted before any call -> 'budget'."""
    rungs = tuple(ladder or _LADDER)
    calls_made = 0
    for provider_name in rungs:
        if not gen_budget.take():
            break  # per-run generation-call ceiling hit mid-ladder
        calls_made += 1
        provider = get_generation_provider(provider_name)
        result = provider.generate(
            GenerationRequest(
                image_bytes=reference_bytes,
                content_type=reference_content_type,
                name=name,
                category=category,
                color=color,
                pattern=pattern,
                brand=brand,
                steering=steering,
            )
        )
        if result is None:
            continue  # provider failure / unavailable / gated-off -> next rung
        verdict = verify_generated_image(
            reference_bytes=reference_bytes,
            reference_content_type=reference_content_type,
            candidate_bytes=result.image_bytes,
            candidate_content_type=result.content_type,
            category=category,
            color=color,
            pattern=pattern,
            name=name,
            budget=verify_budget,
            usage=usage,
        )
        # VERIFY-SKIP vs CONTENT-FAIL (the ladder-advance fix). A skipped verify
        # (429/error/disabled/budget) is NOT the image's fault — advancing to the next,
        # more expensive rung on a transient verify outage is exactly what burned nano.
        # Instead: STORE this already-paid off-cap image and return 'verify_deferred';
        # the caller holds the item pending_retry (masked) and a later self-heal
        # RE-VERIFIES the stored image (no second generation charge). Do NOT touch the
        # next rung.
        if getattr(verdict, "skipped", False):
            url = _store(storage_client, user_id, result.image_bytes, result.content_type)
            if not url:
                break  # storage down -> plain hold (regenerate later)
            return GenOutcome(
                "verify_deferred",
                url=url,
                content_sha256=hashlib.sha256(result.image_bytes).hexdigest(),
                verify_score=0.0,
                cost_usd=float(result.cost_usd or 0.0),
                provider=provider_name,
            )
        # A GENUINE content fail (verify ran; person/extra-garment/bg/framing/match bad)
        # -> advance to the next rung (correct: the image really is unusable).
        if not verdict.matches:
            continue
        url = _store(storage_client, user_id, result.image_bytes, result.content_type)
        if not url:
            break  # passed verify but storage down -> hold
        return GenOutcome(
            "ready",
            url=url,
            content_sha256=hashlib.sha256(result.image_bytes).hexdigest(),
            verify_score=float(verdict.score or 0.0),
            cost_usd=float(result.cost_usd or 0.0),
            provider=provider_name,
        )
    # Budget denied before we could even attempt the first rung -> 'budget' (so callers
    # treat it as capped, not as a verify miss). Any call made but no pass -> 'held'.
    return GenOutcome("budget" if calls_made == 0 else "held")


def generate_from_text(
    *,
    name: Optional[str],
    category: Optional[str],
    color: Optional[str],
    brand: Optional[str],
    storage_client,
    user_id: UUID,
    gen_budget: GenerationBudget,
    verify_budget: VerifyBudget,
    usage: UsageAccumulator,
    steering: Optional[str] = None,
) -> GenOutcome:
    """TEXT→IMAGE product image from attributes (no reference), verify, store.

    The generation rung used when there is no crop / no usable source image at all. Walks
    the T2I LADDER: FLUX.2 [pro] t2i FIRST (off-cap — attempted regardless of the nano
    flag), then nano_banana t2i (on-cap — SKIPPED entirely when nano_fallback_enabled() is
    false). Because there is no reference to compare against, EACH candidate is gated on the
    single-image verify_image PLUS an explicit no-person requirement (person_present must be
    false). NEVER raises.

    NANO FLAG SCOPE: the flag's only job is to gate the nano rung. It NEVER disables the
    off-cap FLUX.2 rung — so an imageless item still generates when nano is off. Budget
    counts ACTUAL generation calls (one take() per rung attempted)."""
    prompt = build_t2i_prompt(name, category, color, brand, steering)
    calls_made = 0
    for rung in _T2I_LADDER:
        if rung == "nano_banana" and not nano_fallback_enabled():
            # On-cap nano t2i: skip ONLY this rung when the flag is off. The off-cap
            # FLUX.2 rung above is never gated on the flag.
            continue
        if not gen_budget.take():
            break  # per-run generation-call ceiling hit
        calls_made += 1
        if rung == "flux2_t2i":
            from app.services.image_generation.flux2_pro import Flux2ProProvider
            result = Flux2ProProvider().generate_text_to_image(prompt)
        else:  # nano_banana
            from app.services.image_generation.nano_banana import generate_text_to_image
            result = generate_text_to_image(prompt)
        if result is None:
            continue  # provider failure / missing key -> next rung
        verdict = verify_image(
            image_bytes=result.image_bytes,
            content_type=result.content_type,
            category=category,
            color=color,
            name=name,
            budget=verify_budget,
            usage=usage,
        )
        # MANDATORY invariant gate (verify_image surfaces these but folds none of them into
        # matches — the email tiers judge REAL retailer images with different rules — so the
        # t2i caller enforces every generated-image hard gate here): expected garment/color
        # match, NO person, NO extra items, off-white background, catalog framing. A miss on
        # ANY of these -> advance to the next rung (the image is genuinely unusable).
        if (
            not verdict.matches
            or verdict.person_present
            or verdict.extra_items_present
            or not verdict.background_offwhite_ok
            or not verdict.framing_ok
        ):
            continue
        url = _store(storage_client, user_id, result.image_bytes, result.content_type)
        if not url:
            break  # passed verify but storage down -> hold (no second gen charge)
        return GenOutcome(
            "ready",
            url=url,
            content_sha256=hashlib.sha256(result.image_bytes).hexdigest(),
            verify_score=float(verdict.score or 0.0),
            cost_usd=float(result.cost_usd or 0.0),
            provider=getattr(result, "provider", rung),
        )
    # No rung produced a verified image. Budget denied before any call -> 'budget'
    # (caller treats as capped); any call attempted but no pass -> 'held'.
    return GenOutcome("budget" if calls_made == 0 else "held")


# Photo-seam Phase 2: build_t2i_prompt moved to app.services.image_generation.prompt so
# the t2i prompt embeds the SAME INVARIANT_BLOCK as the reference prompt (one invariant
# definition, every entry point). Re-exported here for existing importers.
