"""Nano Banana generation provider — Gemini image generation (google-genai SDK).

Reuses the SAME Gemini SDK path as app/services/ai_provider.py (genai.Client +
settings.GEMINI_API_KEY) but keeps its own module-level client so ai_provider.py
stays untouched. One call:

    client.models.generate_content(
        model=settings.NANO_BANANA_MODEL,           # default gemini-3-pro-image-preview
        contents=[{inline_data: cutout}, {text: prompt}],
        config=GenerateContentConfig(response_modalities=["IMAGE"]),
    )

and the FIRST returned inline_data image part is the candidate. If the pinned
SDK version ever rejects response_modalities on the typed config, we fall back
to passing the config as a plain dict (the SDK accepts dict configs).

The SDK talks only to Google's fixed generativelanguage endpoint (no
caller-supplied URLs exist on this path); a per-call timeout is applied via
HttpOptions. Bytes are magic-byte sniffed + size-capped like every provider.
Never raises into callers; logs provider/status/latency only.
"""
from __future__ import annotations

import base64
import logging
import time
from typing import Any, Optional

from google import genai
from google.genai import types

from app.core.config import settings
from app.services.image_generation.base import (
    GenerationRequest,
    GenerationResult,
    sniff_generated_image,
)
from app.services.image_generation.prompt import build_nano_generation_prompt

logger = logging.getLogger(__name__)

# Module-level singleton (mirrors ai_provider's client reuse without touching it).
_client_singleton: Optional[genai.Client] = None


def _get_client() -> genai.Client:
    """Get or create the shared genai client (tests swap this)."""
    global _client_singleton
    if _client_singleton is None:
        kwargs: dict = {}
        if settings.GEMINI_API_KEY:
            kwargs["api_key"] = settings.GEMINI_API_KEY
        try:
            # HttpOptions.timeout is in MILLISECONDS.
            kwargs["http_options"] = types.HttpOptions(
                timeout=int(float(settings.GENERATION_TIMEOUT_SECONDS) * 1000)
            )
            _client_singleton = genai.Client(**kwargs)
        except Exception:
            kwargs.pop("http_options", None)
            _client_singleton = genai.Client(**kwargs)
    return _client_singleton


def _image_config() -> Any:
    """IMAGE-only response config; dict fallback if the SDK rejects the field."""
    try:
        return types.GenerateContentConfig(response_modalities=["IMAGE"])
    except Exception:
        return {"response_modalities": ["IMAGE"]}


def _first_image_bytes(resp: Any) -> Optional[bytes]:
    """Pull the first inline_data image part out of a GenerateContentResponse.

    The SDK may hand back raw bytes or a base64 string (same duality
    ai_provider.py handles). Defensive attribute walking — a malformed/blocked
    response just yields None.
    """
    candidates = getattr(resp, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline = getattr(part, "inline_data", None)
            data = getattr(inline, "data", None)
            if isinstance(data, bytes) and data:
                return data
            if isinstance(data, str) and data:
                try:
                    return base64.b64decode(data)
                except Exception:
                    return None
    return None


class NanoBananaProvider:
    """Gemini image generation ('Nano Banana Pro') via the existing genai SDK."""

    name = "nano_banana"

    def generate(self, req: GenerationRequest) -> Optional[GenerationResult]:
        if not settings.GEMINI_API_KEY:
            logger.info("generation [nano_banana] skipped: GEMINI_API_KEY not set")
            return None

        prompt = build_nano_generation_prompt(req)
        model = settings.NANO_BANANA_MODEL
        started = time.monotonic()
        try:
            client = _get_client()
            resp = client.models.generate_content(
                model=model,
                contents=[
                    {"inline_data": {"mime_type": req.content_type, "data": req.image_bytes}},
                    {"text": prompt},
                ],
                config=_image_config(),
            )
            raw = _first_image_bytes(resp)
        except Exception as exc:
            logger.warning(
                "generation [nano_banana] error (%s) latency=%.1fs",
                type(exc).__name__, time.monotonic() - started,
            )
            return None

        content_type = sniff_generated_image(raw)
        if raw is None or content_type is None:
            logger.warning(
                "generation [nano_banana] failed: no/invalid image part latency=%.1fs",
                time.monotonic() - started,
            )
            return None

        latency = time.monotonic() - started
        logger.info(
            "generation [nano_banana] ok: latency=%.1fs bytes=%d", latency, len(raw)
        )
        return GenerationResult(
            image_bytes=raw,
            content_type=content_type,
            provider=self.name,
            model=model,
            latency_s=latency,
            cost_usd=settings.NANO_BANANA_USD_PER_IMAGE,
            detail="gemini image generation",
        )


def generate_text_to_image(
    prompt: str, *, model: Optional[str] = None
) -> Optional[GenerationResult]:
    """TEXT->IMAGE generation (no reference cutout) via Gemini image gen.

    Additive sibling to NanoBananaProvider.generate: same client, config and
    byte-sniff helpers, but the request carries ONLY a text part — there is no
    input image to condition on. This is offline CURATION tooling (the taste-deck
    archetype job), NOT the product path: the image->image seam
    (GenerationProvider / GenerationRequest) is untouched, so its ISOLATE/PRESERVE
    invariants and tests still hold. Never raises; returns None on any failure.

    The caller owns the prompt in full (build_generation_prompt is garment-restyle
    specific and is NOT used here). Logs provider/status/latency only — never the
    prompt text or image bytes.
    """
    if not settings.GEMINI_API_KEY:
        logger.info("t2i [nano_banana] skipped: GEMINI_API_KEY not set")
        return None

    model = model or settings.NANO_BANANA_MODEL
    started = time.monotonic()
    try:
        client = _get_client()
        resp = client.models.generate_content(
            model=model,
            contents=[{"text": prompt}],
            config=_image_config(),
        )
        raw = _first_image_bytes(resp)
    except Exception as exc:
        logger.warning(
            "t2i [nano_banana] error (%s) latency=%.1fs",
            type(exc).__name__, time.monotonic() - started,
        )
        return None

    content_type = sniff_generated_image(raw)
    if raw is None or content_type is None:
        logger.warning(
            "t2i [nano_banana] failed: no/invalid image part latency=%.1fs",
            time.monotonic() - started,
        )
        return None

    latency = time.monotonic() - started
    logger.info("t2i [nano_banana] ok: latency=%.1fs bytes=%d", latency, len(raw))
    return GenerationResult(
        image_bytes=raw,
        content_type=content_type,
        provider="nano_banana",
        model=model,
        latency_s=latency,
        cost_usd=settings.NANO_BANANA_USD_PER_IMAGE,
        detail="gemini text-to-image",
    )
