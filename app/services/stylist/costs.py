"""Per-turn cost accounting for the stylist chat (reuses the usage helpers).

Token counts come from each Gemini call's ``usage_metadata`` via the existing
``app.gmail_closet.usage.usage_tokens`` reader — recorded, never estimated.
Dollars are computed at THE MODEL THAT RAN EACH CALL (Lite pre-parse, Flash
compose/chat, Pro escalation), mirroring the per-model pricing discipline of
``UsageAccumulator.add_verify``. Rates live in config so pricing edits need no
code change.
"""
from __future__ import annotations

import threading

from app.core.config import settings
from app.gmail_closet.usage import usage_tokens  # re-exported for callers

__all__ = ["chat_gemini_cost", "TurnUsage", "usage_tokens"]


def _per_token(per_1m: float) -> float:
    return float(per_1m) / 1_000_000.0


def chat_gemini_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """USD for one chat-path Gemini call at the rate of the model that ran it.

    Matches on model-name substring so versioned ids (e.g. ``gemini-2.5-pro``)
    and the config seams (STYLIST_MODEL/LITE/ESCALATION) all price correctly.
    Order matters: 'flash-lite' must be tested before 'flash'.
    """
    name = (model or "").lower()
    if "pro" in name:
        rates = (settings.GEMINI_PRO_INPUT_USD_PER_1M, settings.GEMINI_PRO_OUTPUT_USD_PER_1M)
    elif "flash-lite" in name:
        rates = (settings.GEMINI_FLASH_LITE_INPUT_USD_PER_1M, settings.GEMINI_FLASH_LITE_OUTPUT_USD_PER_1M)
    else:  # flash and any unknown default to the Flash rate (the chat default)
        rates = (settings.GEMINI_FLASH_INPUT_USD_PER_1M, settings.GEMINI_FLASH_OUTPUT_USD_PER_1M)
    return input_tokens * _per_token(rates[0]) + output_tokens * _per_token(rates[1])


class TurnUsage:
    """Thread-safe tally of ONE chat turn's model calls, priced per-model at add
    time (token totals alone cannot be repriced across a Lite+Flash+Pro mix)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.input_tokens = 0
        self.output_tokens = 0
        self._cost = 0.0
        self.calls = 0

    def add_call(self, model: str, resp) -> None:
        """Record one Gemini response's real usage_metadata."""
        it, ot = usage_tokens(resp)
        self.add_tokens(model, it, ot)

    def add_tokens(self, model: str, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            it, ot = int(input_tokens or 0), int(output_tokens or 0)
            self.input_tokens += it
            self.output_tokens += ot
            self._cost += chat_gemini_cost(model, it, ot)
            self.calls += 1

    @property
    def cost_usd(self) -> float:
        with self._lock:
            return self._cost
