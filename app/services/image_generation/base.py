"""Image-GENERATION provider seam (Wave 2) — Protocol + Null default + dispatch.

WHERE THIS SITS
---------------
The photo-ingest path produces a garment CUTOUT (already alpha-composited onto a
neutral background). A generation provider turns that cutout into a clean
product-card image via an image-editing model (FLUX Kontext / Seedream / Gemini
"Nano Banana"). Generated images are CANDIDATES ONLY — a separate vision-verify
gate decides whether a candidate is ever shown. Nothing in the product flow calls
this seam yet; the bake-off script does.

THE SEAM (mirrors FeedProvider — app/gmail_closet/feed_provider.py)
-------------------------------------------------------------------
    GenerationProvider.generate(GenerationRequest) -> GenerationResult | None

Providers are selected by settings.GENERATION_PROVIDER (or an explicit ``name``
override, for the bake-off) via get_generation_provider(). With
GENERATION_ENABLED false — the shipped default — dispatch returns the
NullGenerationProvider, so the seam is a guaranteed no-op until deliberately
turned on. Unknown provider names and providers whose API key is missing also
fall back to Null (warn, never raise).

PROVIDER CONTRACT (see GenerationProvider docstring)
----------------------------------------------------
Return None on ANY failure — never raise into callers. Validate returned bytes
(magic-byte sniff + size cap) before trusting them. Log provider + status +
latency only — never prompt or image contents.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

from app.core.config import settings
from app.utils.image_validation import sniff_image_format

logger = logging.getLogger(__name__)

# Hard ceiling on bytes accepted back from ANY provider (anti-amplification /
# pre-decode guard). Product-card images are ~100KB-2MB; 20MB is generous.
MAX_GENERATED_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class GenerationRequest:
    """One generation job: the reference cutout + optional attribute hints.

    image_bytes  : the reference garment cutout (PRE-MASKED — alpha-composited
                   onto a neutral background upstream; there is no mask field).
    content_type : MIME type of image_bytes (e.g. 'image/png').
    name/category/color/pattern/brand : optional item attributes. Only
                   category/color/pattern feed the prompt (see prompt.py);
                   name/brand are carried for reporting.
    steering     : OPTIONAL untrusted free-text correction from the user
                   (Regenerate "what was wrong?"). Fed to the prompt ONLY as a
                   fenced garment-description hint (prompt.py) — it may describe the
                   garment's true appearance but cannot override the ISOLATE/NO-ADD/
                   NO-SCENE rules or the mandatory verify gate.
    """
    image_bytes: bytes
    content_type: str
    name: Optional[str] = None
    category: Optional[str] = None
    color: Optional[str] = None
    pattern: Optional[str] = None
    brand: Optional[str] = None
    steering: Optional[str] = None


@dataclass
class GenerationResult:
    """A generated CANDIDATE image (not trusted until it passes verify).

    image_bytes  : sniffed, size-capped image bytes from the provider.
    content_type : canonical MIME derived from the magic bytes (never the
                   provider's claim).
    provider     : the provider seam name (e.g. 'flux_kontext').
    model        : the concrete model that produced the image.
    latency_s    : wall-clock seconds for the full call (submit+poll+download).
    cost_usd     : per-image cost from the settings rate, None if unknown.
    detail       : short, redaction-safe note for reports.
    """
    image_bytes: bytes
    content_type: str
    provider: str
    model: str
    latency_s: float
    cost_usd: Optional[float]
    detail: str = ""


@runtime_checkable
class GenerationProvider(Protocol):
    """A cutout -> product-card-candidate generator.

    Implementations MUST:
      * return None on ANY failure (network, moderation, timeout, bad payload)
        — NEVER raise into callers;
      * validate returned bytes are a real image via a magic-byte sniff
        (app.utils.image_validation.sniff_image_format) and enforce the
        MAX_GENERATED_BYTES size cap before returning them;
      * call only their fixed https API hosts (never caller-supplied URLs);
      * never log prompt or image contents — provider + status + latency only.

    OPTIONAL account-skip convention: a provider MAY expose a sticky
    ``unavailable_reason: Optional[str]`` attribute, set when the FAILURE is an
    account state (exhausted balance, locked account) rather than a model/request
    failure. generate() still returns None, but tools that tally per-provider
    stats (the bake-off) read this via getattr() to bucket the miss as SKIPPED —
    like a missing key — instead of counting it as a generation failure that
    would drag the pass-rate. Absent/None means "no account-level skip".
    """

    name: str

    def generate(self, req: GenerationRequest) -> Optional[GenerationResult]:
        ...


class NullGenerationProvider:
    """The shipped default: generation not configured -> every call is a miss.

    Keeps the seam a safe no-op until a real provider is deliberately enabled.
    Never raises.
    """

    name = "null"

    def generate(self, req: GenerationRequest) -> Optional[GenerationResult]:
        return None


class GenerationBudget:
    """Per-run cap on generation calls (cost guard). Thread-safe.

    take() returns True and consumes one unit while budget remains, else False.
    Same shape as VerifyBudget/SearchBudget so the bake-off can share the idiom.
    """

    def __init__(self, limit: int):
        self._lock = threading.Lock()
        self._remaining = max(0, int(limit))

    def take(self) -> bool:
        with self._lock:
            if self._remaining <= 0:
                return False
            self._remaining -= 1
            return True

    @property
    def remaining(self) -> int:
        with self._lock:
            return self._remaining


def nano_fallback_enabled() -> bool:
    """True when the on-cap nano_banana generator is allowed (default False).

    THE single predicate both nano gates read (get_generation_provider for the ladder,
    generate_from_text for t2i) so the flag has exactly one meaning everywhere."""
    return bool(settings.GENERATION_NANO_FALLBACK_ENABLED)


def error_detail(exc: BaseException) -> str:
    """Redaction-safe one-liner for a provider-call exception: exception class +
    HTTP status code when one is cheaply available. NEVER includes the response
    body, prompt, or image bytes — a status code alone is enough to distinguish
    'transient rate limit' from 'auth/request-shape bug' in logs without risking
    a leaked API error body. Best-effort: falls back to just the class name."""
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)          # httpx.HTTPStatusError has .response
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    if status is None:
        status = getattr(exc, "status", None)            # google.genai errors.ClientError
    return f"{name} status={status}" if status is not None else name


def sniff_generated_image(data: Optional[bytes]) -> Optional[str]:
    """Shared provider-output gate: real image bytes under the size cap, or None.

    Returns the canonical content-type ('image/jpeg' | 'image/png' | 'image/webp')
    derived from the MAGIC BYTES — a provider's declared content type is never
    trusted. None means the bytes must be discarded (the provider returns None).
    """
    if not data or len(data) > MAX_GENERATED_BYTES:
        return None
    fmt = sniff_image_format(data)
    if fmt is None:
        return None
    return f"image/{fmt}"


# Provider name -> the settings attribute holding its API key. Also the registry
# of KNOWN provider names for dispatch + the bake-off listing.
_PROVIDER_KEY_SETTING = {
    "flux2_pro": "BFL_API_KEY",
    "flux_kontext": "BFL_API_KEY",
    "seedream": "FAL_API_KEY",
    "nano_banana": "GEMINI_API_KEY",
}


def list_available_providers() -> dict[str, bool]:
    """Provider name -> whether its API key is configured (for the bake-off)."""
    return {
        name: bool(getattr(settings, key_attr, None))
        for name, key_attr in _PROVIDER_KEY_SETTING.items()
    }


def get_generation_provider(name: Optional[str] = None) -> GenerationProvider:
    """Return the active GenerationProvider (Null unless deliberately configured).

    Dispatches on ``name`` (explicit override — the bake-off iterating providers)
    or settings.GENERATION_PROVIDER. Falls back to NullGenerationProvider when:
      * GENERATION_ENABLED is false and no explicit name was given (shipped state);
      * the resolved name is not a known provider (warn);
      * the provider's API key is not configured (warn).
    Never raises.
    """
    if name is None and not settings.GENERATION_ENABLED:
        return NullGenerationProvider()

    resolved = (name or settings.GENERATION_PROVIDER or "").strip().lower()
    # HARD NANO CEILING — the single dispatch gate. nano_banana (on-cap, $0.134) is
    # NEVER instantiated unless GENERATION_NANO_FALLBACK_ENABLED is true. Every ladder
    # caller resolves each rung through here, so one gate covers worker / self-heal /
    # manual / backfill / regenerate. (The t2i entry — generate_from_text — runs its own
    # ladder and gates ONLY its nano rung with this flag; its off-cap FLUX.2 t2i rung is
    # never gated here.)
    if resolved == "nano_banana" and not nano_fallback_enabled():
        logger.info("generation: nano_banana fallback DISABLED -> null provider (off-cap only)")
        return NullGenerationProvider()
    key_attr = _PROVIDER_KEY_SETTING.get(resolved)
    if key_attr is None:
        logger.warning("generation: unknown provider %r -> null provider", resolved)
        return NullGenerationProvider()
    if not getattr(settings, key_attr, None):
        logger.warning(
            "generation: provider %s missing credential %s -> null provider",
            resolved, key_attr,
        )
        return NullGenerationProvider()

    # Imports are local so importing the seam never drags in provider deps
    # (e.g. google-genai) unless that provider is actually selected.
    if resolved == "flux2_pro":
        from app.services.image_generation.flux2_pro import Flux2ProProvider
        return Flux2ProProvider()
    if resolved == "flux_kontext":
        from app.services.image_generation.flux_kontext import FluxKontextProvider
        return FluxKontextProvider()
    if resolved == "seedream":
        from app.services.image_generation.seedream import SeedreamProvider
        return SeedreamProvider()
    from app.services.image_generation.nano_banana import NanoBananaProvider
    return NanoBananaProvider()
