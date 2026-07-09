"""FLUX.2 [pro] generation provider (Black Forest Labs API) — THE RUNG-1 PROVIDER.

Supersedes flux_kontext on the happy path: FLUX.2 [pro] is BFL's current frontier
image model (validated in the BFL playground for our garment-card use). flux_kontext
stays selectable via GENERATION_PROVIDER='flux_kontext'; nano_banana is the on-cap
rung-2 verify-fail retry.

API SHAPE (confirmed against docs.bfl.ai / bfl.ai, 2026-07):
  1. SUBMIT  POST https://api.bfl.ai/v1/flux-2-pro
             headers {"x-key": BFL_API_KEY}, JSON body with the prompt + the base64
             REFERENCE image in `input_image` (FLUX.2 takes up to 8 references via
             input_image, input_image_2..8; we send exactly one — the garment cutout).
             `input_image` accepts a raw base64 string OR a URL; we send base64, the
             same way flux_kontext does. Response: {"id": ..., "polling_url": ...}.
  2. POLL    GET <polling_url> (params {"id": id}, same x-key) every ~1.5s until the
             GENERATION_TIMEOUT_SECONDS deadline. status "Ready" -> result["sample"]
             is a SIGNED delivery URL (valid ~10 minutes). "Error"/"Failed"/"Content
             Moderated"/"Request Moderated"/"Task not found" are terminal -> None.
  3. FETCH   GET the signed sample URL (no auth header — it is pre-signed) and
             sniff + size-cap the bytes.

The response/poll/delivery shape is IDENTICAL to FLUX.1 Kontext (same BFL account);
only the endpoint path, model slug, and per-image cost differ. Reference-image
conditioning therefore works exactly like the kontext path (base64 in `input_image`),
so the on-model->clean-product routing and POST /closet/{id}/regenerate condition on
the reference correctly. A broken ref path still just returns None -> the ladder falls
to nano and, ultimately, the crop is never leaked (the verify gate is the backstop).

HOST ALLOWLIST: every URL we follow (polling_url AND the delivery URL) must be https
on bfl.ai or a *.bfl.ai subdomain (api.bfl.ai + the region delivery hosts). Anything
else is dropped. Never raises into callers; logs provider/status/latency only.
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
# Pinned model snapshot; 'flux-2-pro-preview' tracks the latest. FLUX.2 shares BFL's
# submit/poll/deliver conventions with kontext, so only these three lines differ.
_SUBMIT_URL = "https://api.bfl.ai/v1/flux-2-pro"
_MODEL = "flux-2-pro"
_OUTPUT_FORMAT = "jpeg"
_SAFETY_TOLERANCE = 2
_POLL_INTERVAL_S = 1.5
# Terminal poll statuses that mean the request will never become Ready.
_TERMINAL_FAILURE_STATUSES = frozenset(
    {"Error", "Failed", "Content Moderated", "Request Moderated", "Task not found"}
)
# Apex domains we will follow polling/delivery URLs on (https only).
_ALLOWED_APEX_DOMAINS = ("bfl.ai",)


def _is_allowed_url(url: object) -> bool:
    """True only for https URLs on the fixed bfl.ai family (api + delivery)."""
    if not isinstance(url, str):
        return False
    try:
        parsed = httpx.URL(url)
    except Exception:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.host or "").lower()
    return any(host == apex or host.endswith("." + apex) for apex in _ALLOWED_APEX_DOMAINS)


def _client() -> httpx.Client:
    """Fresh client with the explicit per-request timeout (tests swap this)."""
    return httpx.Client(timeout=float(settings.GENERATION_TIMEOUT_SECONDS))


class Flux2ProProvider:
    """BFL FLUX.2 [pro] — submit -> poll -> fetch signed delivery URL."""

    name = "flux2_pro"

    def generate(self, req: GenerationRequest) -> Optional[GenerationResult]:
        if not settings.BFL_API_KEY:
            logger.info("generation [flux2_pro] skipped: BFL_API_KEY not set")
            return None

        prompt = build_generation_prompt(req)
        started = time.monotonic()
        deadline = started + float(settings.GENERATION_TIMEOUT_SECONDS)
        try:
            with _client() as http:
                image_bytes, content_type = self._run(http, prompt, req, deadline)
        except Exception as exc:
            logger.warning(
                "generation [flux2_pro] error (%s) latency=%.1fs",
                type(exc).__name__, time.monotonic() - started,
            )
            return None
        if image_bytes is None or content_type is None:
            return None

        latency = time.monotonic() - started
        logger.info(
            "generation [flux2_pro] ok: latency=%.1fs bytes=%d", latency, len(image_bytes)
        )
        return GenerationResult(
            image_bytes=image_bytes,
            content_type=content_type,
            provider=self.name,
            model=_MODEL,
            latency_s=latency,
            cost_usd=settings.FLUX2_PRO_USD_PER_IMAGE,
            detail="bfl flux-2-pro",
        )

    # -- internal ----------------------------------------------------------

    def _run(
        self, http: httpx.Client, prompt: str, req: GenerationRequest, deadline: float
    ) -> Tuple[Optional[bytes], Optional[str]]:
        headers = {"x-key": settings.BFL_API_KEY or "", "Content-Type": "application/json"}

        # 1. SUBMIT — the garment cutout is the reference image (input_image, base64).
        submit = http.post(
            _SUBMIT_URL,
            headers=headers,
            json={
                "prompt": prompt,
                "input_image": base64.b64encode(req.image_bytes).decode("ascii"),
                "output_format": _OUTPUT_FORMAT,
                "safety_tolerance": _SAFETY_TOLERANCE,
            },
        )
        submit.raise_for_status()
        body = submit.json()
        request_id = body.get("id")
        polling_url = body.get("polling_url")
        if not request_id or not _is_allowed_url(polling_url):
            logger.warning("generation [flux2_pro] failed: bad submit response")
            return None, None

        # 2. POLL (attempt counter is log-safe; the payload never is)
        attempt = 0
        while time.monotonic() < deadline:
            attempt += 1
            poll = http.get(polling_url, headers={"x-key": settings.BFL_API_KEY or ""},
                            params={"id": request_id})
            poll.raise_for_status()
            data = poll.json()
            status = str(data.get("status") or "")
            if status == "Ready":
                sample_url = (data.get("result") or {}).get("sample")
                return self._fetch_sample(http, sample_url, attempt)
            if status in _TERMINAL_FAILURE_STATUSES:
                logger.info(
                    "generation [flux2_pro] failed: status=%s attempt=%d", status, attempt
                )
                return None, None
            # Pending/Queued/etc. -> keep polling until the deadline.
            time.sleep(max(0.0, min(_POLL_INTERVAL_S, deadline - time.monotonic())))

        logger.info("generation [flux2_pro] failed: poll timeout after %d attempt(s)", attempt)
        return None, None

    def _fetch_sample(
        self, http: httpx.Client, sample_url: object, attempt: int
    ) -> Tuple[Optional[bytes], Optional[str]]:
        """3. FETCH the signed delivery URL (bfl.ai family only), sniff + cap."""
        if not _is_allowed_url(sample_url):
            logger.warning(
                "generation [flux2_pro] failed: delivery host not allowlisted"
            )
            return None, None
        # Signed URL — deliberately NO x-key header on the delivery fetch.
        resp = http.get(str(sample_url))
        resp.raise_for_status()
        content_type = sniff_generated_image(resp.content)
        if content_type is None:
            logger.warning(
                "generation [flux2_pro] failed: invalid/oversize image bytes attempt=%d",
                attempt,
            )
            return None, None
        return resp.content, content_type
