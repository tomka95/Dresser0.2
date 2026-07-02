"""Per-sync / per-user cost tracking for the Gmail ingest pipeline.

WHAT IT MEASURES (recorded, never estimated)
---------------------------------------------
Real usage from each provider, attributed to the ingest_run (sync) and thus the user:
  * Gemini EXTRACTION (base Flash-Lite + Flash escalation) — input/output token counts
    from each call's usage_metadata, summed in the extractor and written by the
    extraction service.
  * Gemini VISION-VERIFY — input/output tokens from each verify call's usage_metadata,
    accumulated in the background image-fill pass. The single-image pass runs Flash-Lite;
    the generated-image reference-vs-candidate PAIR pass runs the pricier
    GENERATION_VERIFY_MODEL (Flash), and each call is priced at the model that ran it.
  * SERPER shopping search — one credit per ISSUED query, counted in shopping_search.

Dollars are computed from those recorded units × the editable per-unit rates in
config (GEMINI_*_USD_PER_1M, SERPER_USD_PER_CREDIT), broken out so we can see which
tier drives cost: extract_cost_usd + verify_cost_usd + search_cost_usd = cost_usd.

SAFETY
------
Cost rows hold COUNTS + DOLLARS only — never email content. Every persistence helper
is BEST-EFFORT (wrapped, never raises) so a cost-logging failure can never break a
sync, exactly like the background image fill.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.core.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rates (read from config so pricing edits need no code change)
# ---------------------------------------------------------------------------

def _per_token(per_1m: float) -> float:
    return float(per_1m) / 1_000_000.0


def gemini_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """USD for one Gemini call at the rate of the model that actually ran it.

    The escalation model (Flash) is pricier; everything else (extraction base +
    vision-verify) bills at Flash-Lite. Rates come from config.
    """
    if model and model == settings.GEMINI_EXTRACT_ESCALATION_MODEL:
        return (
            input_tokens * _per_token(settings.GEMINI_FLASH_INPUT_USD_PER_1M)
            + output_tokens * _per_token(settings.GEMINI_FLASH_OUTPUT_USD_PER_1M)
        )
    return (
        input_tokens * _per_token(settings.GEMINI_FLASH_LITE_INPUT_USD_PER_1M)
        + output_tokens * _per_token(settings.GEMINI_FLASH_LITE_OUTPUT_USD_PER_1M)
    )


def gemini_flash_lite_cost(input_tokens: int, output_tokens: int) -> float:
    """USD if these tokens billed entirely at Flash-Lite rates (the headline rate)."""
    return (
        input_tokens * _per_token(settings.GEMINI_FLASH_LITE_INPUT_USD_PER_1M)
        + output_tokens * _per_token(settings.GEMINI_FLASH_LITE_OUTPUT_USD_PER_1M)
    )


def serper_cost(credits: int) -> float:
    """USD for ``credits`` issued Serper queries."""
    return float(credits) * float(settings.SERPER_USD_PER_CREDIT)


def usage_tokens(resp) -> tuple[int, int]:
    """Pull (input, output) token counts from a Gemini response's usage_metadata.

    Best-effort: returns (0, 0) when the field is absent. Same field names the
    extractor reads (prompt_token_count / candidates_token_count).
    """
    usage = getattr(resp, "usage_metadata", None)
    if usage is None:
        return 0, 0
    return (
        int(getattr(usage, "prompt_token_count", 0) or 0),
        int(getattr(usage, "candidates_token_count", 0) or 0),
    )


# ---------------------------------------------------------------------------
# Live accumulator (for the verify + search calls deep in the background fill)
# ---------------------------------------------------------------------------

class UsageAccumulator:
    """Thread-safe tally of vision-verify tokens + Serper credits for one run.

    Threaded down to verify_image() / search_products() so each call records its own
    REAL usage at the source. Extraction tokens are NOT accumulated here — the
    extractor already returns per-email token totals which the extraction service
    sums directly. ``None`` is a valid argument everywhere (recording simply off).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.verify_input_tokens = 0
        self.verify_output_tokens = 0
        # Cost accrued PER MODEL at add time (not recomputed from token totals):
        # the single-image pass runs Flash-Lite, the generated-image pair pass runs
        # the pricier GENERATION_VERIFY_MODEL (Flash). Pricing at add time keeps a
        # mix of the two correct — token totals alone can't be repriced.
        self._verify_cost = 0.0
        self.serper_credits = 0

    def add_verify(
        self, input_tokens: int, output_tokens: int, model: Optional[str] = None
    ) -> None:
        """Record one verify call's tokens, priced at the MODEL THAT RAN IT.

        Token totals accumulate for the count columns; cost accrues per-model so
        the generated-image pair pass (GENERATION_VERIFY_MODEL = Flash) is billed
        at Flash, not under-reported at the single-image Flash-Lite rate. ``model``
        defaults to the single-image verify model (GMAIL_VERIFY_MODEL).
        """
        with self._lock:
            it, ot = int(input_tokens or 0), int(output_tokens or 0)
            self.verify_input_tokens += it
            self.verify_output_tokens += ot
            self._verify_cost += gemini_cost(model or settings.GMAIL_VERIFY_MODEL, it, ot)

    def add_serper(self, credits: int = 1) -> None:
        with self._lock:
            self.serper_credits += int(credits or 0)

    @property
    def verify_cost_usd(self) -> float:
        """Sum of each verify call's cost at the model that ran it (per-model priced)."""
        with self._lock:
            return self._verify_cost

    @property
    def search_cost_usd(self) -> float:
        return serper_cost(self.serper_credits)


# ---------------------------------------------------------------------------
# Persistence (best-effort — never raises into a sync)
# ---------------------------------------------------------------------------

def _recompute_total(run) -> None:
    """cost_usd = extract + verify + search.

    Numeric columns read back as Decimal but the cost helpers return float, and
    Decimal + float raises TypeError — so coerce every term to float first.
    """
    run.cost_usd = (
        float(run.extract_cost_usd or 0)
        + float(run.verify_cost_usd or 0)
        + float(run.search_cost_usd or 0)
    )


def record_extraction_usage(
    db,
    sync_id: Optional[UUID],
    *,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
) -> None:
    """Write extraction (Gemini base+escalation) usage onto the sync's ingest_run.

    Called once at the end of the extraction phase with the run's summed token totals
    and realistic per-model cost. Best-effort.
    """
    if sync_id is None:
        return
    try:
        from app.models import IngestRun

        run = db.query(IngestRun).filter(IngestRun.sync_id == sync_id).first()
        if run is None:
            return
        run.gemini_input_tokens = int(input_tokens or 0)
        run.gemini_output_tokens = int(output_tokens or 0)
        run.extract_cost_usd = float(cost_usd or 0.0)
        _recompute_total(run)
        db.commit()
    except Exception as exc:
        logger.warning("record_extraction_usage failed: %s", type(exc).__name__)
        try:
            db.rollback()
        except Exception:
            pass


def record_fill_usage(db, sync_id: Optional[UUID], acc: UsageAccumulator) -> None:
    """Write vision-verify + Serper usage (from the background fill) onto the run.

    Adds to any existing values so a re-run / multiple fills on one sync accumulate.
    Best-effort.
    """
    if sync_id is None or acc is None:
        return
    try:
        from app.models import IngestRun

        run = db.query(IngestRun).filter(IngestRun.sync_id == sync_id).first()
        if run is None:
            return
        run.verify_input_tokens = (run.verify_input_tokens or 0) + acc.verify_input_tokens
        run.verify_output_tokens = (run.verify_output_tokens or 0) + acc.verify_output_tokens
        run.serper_credits = (run.serper_credits or 0) + acc.serper_credits
        # ADD the accumulator's per-model-priced cost (do NOT reprice token totals
        # at one rate — that would under-bill the Flash pair pass). Identical to the
        # old recompute when every verify ran on one model (the Gmail single-image
        # path today), and correct once the Flash pair pass also records here.
        run.verify_cost_usd = float(run.verify_cost_usd or 0) + acc.verify_cost_usd
        run.search_cost_usd = serper_cost(run.serper_credits)
        _recompute_total(run)
        db.commit()
    except Exception as exc:
        logger.warning("record_fill_usage failed: %s", type(exc).__name__)
        try:
            db.rollback()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Per-user rollup (the "what has user X cost us" read path)
# ---------------------------------------------------------------------------

def _f(v) -> float:
    try:
        return round(float(v or 0), 6)
    except (TypeError, ValueError):
        return 0.0


def _run_costs(run) -> Dict[str, Any]:
    return {
        "sync_id": str(run.sync_id),
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "gemini_input_tokens": int(run.gemini_input_tokens or 0),
        "gemini_output_tokens": int(run.gemini_output_tokens or 0),
        "verify_input_tokens": int(run.verify_input_tokens or 0),
        "verify_output_tokens": int(run.verify_output_tokens or 0),
        "serper_credits": int(run.serper_credits or 0),
        "extract_cost_usd": _f(run.extract_cost_usd),
        "verify_cost_usd": _f(run.verify_cost_usd),
        "search_cost_usd": _f(run.search_cost_usd),
        "cost_usd": _f(run.cost_usd),
    }


def get_user_cost_summary(db, user_id: UUID) -> Dict[str, Any]:
    """Per-user cost rollup: totals across all of the user's syncs + a per-sync list.

    Answers "what has user X cost us, total and per sync", broken out by tier
    (extract / verify / search). Pure read; counts + dollars only.
    """
    from app.models import IngestRun

    runs: List[Any] = (
        db.query(IngestRun)
        .filter(IngestRun.user_id == user_id)
        .order_by(IngestRun.started_at.desc())
        .all()
    )
    per_run = [_run_costs(r) for r in runs]

    totals = {
        "runs": len(per_run),
        "gemini_input_tokens": sum(r["gemini_input_tokens"] for r in per_run),
        "gemini_output_tokens": sum(r["gemini_output_tokens"] for r in per_run),
        "verify_input_tokens": sum(r["verify_input_tokens"] for r in per_run),
        "verify_output_tokens": sum(r["verify_output_tokens"] for r in per_run),
        "serper_credits": sum(r["serper_credits"] for r in per_run),
        "extract_cost_usd": round(sum(r["extract_cost_usd"] for r in per_run), 6),
        "verify_cost_usd": round(sum(r["verify_cost_usd"] for r in per_run), 6),
        "search_cost_usd": round(sum(r["search_cost_usd"] for r in per_run), 6),
        "cost_usd": round(sum(r["cost_usd"] for r in per_run), 6),
    }
    return {"user_id": str(user_id), "totals": totals, "runs": per_run}
