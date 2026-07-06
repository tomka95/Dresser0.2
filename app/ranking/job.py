"""Nightly wardrobe-gap job: per-user run + upsert (Wave F2).

DB-bound driver around the pure ``app.ranking.gap`` core. Per user: load the closet + its
item embeddings + profile, pick the top-K taste candidates (pgvector), compute each
candidate's marginal outfit unlock over the context grid, and upsert user_wardrobe_gap.

$0 API: pgvector reads + numpy + the pure assembler — no LLM. The dev script
(scripts/dev_wardrobe_gap.py) loops this over users, committing per user so one user's
failure never poisons the batch.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from uuid import UUID

import numpy as np
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import ItemEmbedding, UserWardrobeGap
from app.ranking import features as F
from app.ranking.gap import compute_wardrobe_gaps
from app.ranking.types import RankingConfig
from app.services.closet_service import list_closet_items
from app.services.stylist.profile import assemble_profile

logger = logging.getLogger(__name__)


@dataclass
class WardrobeGapStats:
    closet_items: int = 0
    candidates_scored: int = 0
    rows_written: int = 0
    rows_deleted: int = 0
    total_unlocks: int = 0
    max_unlock: int = 0
    elapsed: float = 0.0
    cost_usd: float = 0.0        # always $0 — pure CPU, no API. Kept for skeleton parity.
    error: Optional[str] = None


def _closet_embeddings(db: Session, user_id: UUID) -> Dict[str, np.ndarray]:
    rows = (
        db.query(ItemEmbedding.item_id, ItemEmbedding.embedding)
        .filter(
            ItemEmbedding.user_id == user_id,
            ItemEmbedding.model == settings.EMBEDDING_MODEL,
            ItemEmbedding.version == settings.EMBEDDING_VERSION,
        )
        .all()
    )
    out: Dict[str, np.ndarray] = {}
    for item_id, emb in rows:
        if emb is not None:
            out[str(item_id)] = np.asarray(emb, dtype=np.float64)
    return out


def run_wardrobe_gap(
    db: Session,
    user_id: UUID,
    *,
    cfg: Optional[RankingConfig] = None,
) -> WardrobeGapStats:
    """Compute + upsert the user's wardrobe-gap rows. Adds to the session; the CALLER commits
    (per-user isolation). On any error the stats carry ``error`` and the session is rolled
    back by the caller — the row set is left as-is (never partially clobbered)."""
    cfg = cfg or RankingConfig.from_settings(settings)
    stats = WardrobeGapStats()
    started = time.monotonic()
    try:
        closet = list_closet_items(db, user_id)
        stats.closet_items = len(closet)
        emb_by_id = _closet_embeddings(db, user_id)
        profile = assemble_profile(db, user_id)

        blend = F.taste_blend(db, user_id, cfg)
        candidates = F.top_taste_products(db, blend, cfg.gap_candidate_k)
        stats.candidates_scored = len(candidates)
        if not candidates:
            stats.elapsed = time.monotonic() - started
            return stats

        results = compute_wardrobe_gaps(closet, emb_by_id, candidates, profile, cfg)

        # Upsert one row per (user, product); refresh unlock_count + gap_context + computed_at.
        existing = {
            str(r.product_id): r
            for r in db.query(UserWardrobeGap).filter(UserWardrobeGap.user_id == user_id).all()
        }
        seen: set = set()
        for res in results:
            seen.add(res.product_id)
            stats.total_unlocks += res.unlock_count
            stats.max_unlock = max(stats.max_unlock, res.unlock_count)
            row = existing.get(res.product_id)
            if row is None:
                db.add(
                    UserWardrobeGap(
                        user_id=user_id,
                        product_id=UUID(res.product_id),
                        unlock_count=res.unlock_count,
                        gap_context=res.gap_context,
                    )
                )
            else:
                row.unlock_count = res.unlock_count
                row.gap_context = res.gap_context
            stats.rows_written += 1

        # Drop stale rows for products no longer in the candidate pool (keep the table fresh).
        for pid, row in existing.items():
            if pid not in seen:
                db.delete(row)
                stats.rows_deleted += 1

    except Exception as exc:  # never raises to the batch loop
        stats.error = f"{type(exc).__name__}: {exc}"
        logger.exception("wardrobe-gap run failed for user %s", user_id)
    stats.elapsed = time.monotonic() - started
    return stats
