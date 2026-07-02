"""Seedream v4 edit generation provider (ByteDance model via fal.ai).

API SHAPE (confirmed against fal.ai model docs, 2026-07):
  SYNCHRONOUS  POST https://fal.run/fal-ai/bytedance/seedream/v4/edit
               headers {"Authorization": "Key <FAL_API_KEY>"}, JSON body with
               the prompt + the reference image as a base64 DATA URI in
               image_urls (fal decodes data URIs server-side — no upload step).
               Response: {"images": [{"url": ...}], ...} where url is either an
               https fal CDN URL or itself a data URI.

RESULT HANDLING: a data-URI result is decoded locally; an https result is only
fetched when its host is on the fixed fal family allowlist (fal.media / fal.run
/ fal.ai + subdomains). Either way the bytes are magic-byte sniffed and
size-capped before being trusted. Extend _ALLOWED_APEX_DOMAINS if fal moves its
result CDN.

The endpoint path + payload live in module constants so a live smoke test can
correct them without touching the flow. Never raises into callers; logs
provider/status/latency only (no prompts, no image bytes, no URLs).
"""
from __future__ import annotations

import base64
import logging
import time
from typing import Optional, Tuple

import httpx

from app.core.config import settings
from app.services.image_generation.base import (
    GenerationRequest,
    GenerationResult,
    sniff_generated_image,
)
from app.services.image_generation.prompt import build_generation_prompt

logger = logging.getLogger(__name__)

# --- API shape (small constants, trivial to correct after a live smoke test) ---
_ENDPOINT_URL = "https://fal.run/fal-ai/bytedance/seedream/v4/edit"
_MODEL = "seedream-v4-edit"
_IMAGE_SIZE = {"width": 1024, "height": 1024}
# Apex domains whose https result URLs we will fetch (fal's result CDN family).
_ALLOWED_APEX_DOMAINS = ("fal.media", "fal.run", "fal.ai")


def _is_allowed_url(url: str) -> bool:
    """True only for https URLs on the fixed fal family (result CDN)."""
    try:
        parsed = httpx.URL(url)
    except Exception:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.host or "").lower()
    return any(host == apex or host.endswith("." + apex) for apex in _ALLOWED_APEX_DOMAINS)


def _decode_data_uri(uri: str) -> Optional[bytes]:
    """Decode a base64 data URI ('data:<mime>;base64,<payload>'), else None."""
    header, sep, payload = uri.partition(",")
    if not sep or not header.startswith("data:") or ";base64" not in header:
        return None
    try:
        return base64.b64decode(payload, validate=True)
    except Exception:
        return None


def _client() -> httpx.Client:
    """Fresh client with the explicit per-request timeout (tests swap this)."""
    return httpx.Client(timeout=float(settings.GENERATION_TIMEOUT_SECONDS))


class SeedreamProvider:
    """fal.ai Seedream v4 edit — one synchronous POST, data-URI in and out."""

    name = "seedream"

    def generate(self, req: GenerationRequest) -> Optional[GenerationResult]:
        if not settings.FAL_API_KEY:
            logger.info("generation [seedream] skipped: FAL_API_KEY not set")
            return None

        prompt = build_generation_prompt(req)
        started = time.monotonic()
        try:
            with _client() as http:
                image_bytes, content_type = self._run(http, prompt, req)
        except Exception as exc:
            logger.warning(
                "generation [seedream] error (%s) latency=%.1fs",
                type(exc).__name__, time.monotonic() - started,
            )
            return None
        if image_bytes is None or content_type is None:
            return None

        latency = time.monotonic() - started
        logger.info(
            "generation [seedream] ok: latency=%.1fs bytes=%d", latency, len(image_bytes)
        )
        return GenerationResult(
            image_bytes=image_bytes,
            content_type=content_type,
            provider=self.name,
            model=_MODEL,
            latency_s=latency,
            cost_usd=settings.SEEDREAM_USD_PER_IMAGE,
            detail="fal seedream v4 edit",
        )

    # -- internal ----------------------------------------------------------

    def _run(
        self, http: httpx.Client, prompt: str, req: GenerationRequest
    ) -> Tuple[Optional[bytes], Optional[str]]:
        b64 = base64.b64encode(req.image_bytes).decode("ascii")
        resp = http.post(
            _ENDPOINT_URL,
            headers={"Authorization": f"Key {settings.FAL_API_KEY}"},
            json={
                "prompt": prompt,
                "image_urls": [f"data:{req.content_type};base64,{b64}"],
                "image_size": _IMAGE_SIZE,
                "num_images": 1,
                "enable_safety_checker": True,
            },
        )
        resp.raise_for_status()
        images = resp.json().get("images") or []
        first = images[0] if images and isinstance(images[0], dict) else {}
        url = first.get("url")
        if not isinstance(url, str) or not url:
            logger.warning("generation [seedream] failed: no image in response")
            return None, None

        # Result may be a data URI (decode locally) or an https fal CDN URL.
        if url.startswith("data:"):
            raw = _decode_data_uri(url)
        elif _is_allowed_url(url):
            fetched = http.get(url)
            fetched.raise_for_status()
            raw = fetched.content
        else:
            logger.warning("generation [seedream] failed: result host not allowlisted")
            return None, None

        content_type = sniff_generated_image(raw)
        if content_type is None:
            logger.warning("generation [seedream] failed: invalid/oversize image bytes")
            return None, None
        return raw, content_type
