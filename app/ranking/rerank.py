"""Re-rank layer: MMR diversity + category calibration + exploration (Wave F2).

Pure and DETERMINISTIC. Relevance is the Stage-1 score; this layer reshapes the *order* so
the feed is not a monotone taste-cosine list:

  * MMR (λ)          — greedy max of  λ·rel(i) − (1−λ)·max_sim(i, already-picked)  over
                       product embeddings, so near-duplicate products don't stack.
  * category calibration — a penalty on a candidate whose category is already
                       over-represented vs the user's target mix (closet + occasions), so the
                       feed's category shares track what the user actually wears.
  * exploration (ε)  — ~15–20% of positions are handed to lower-ranked, category-NOVEL
                       candidates (adjacent archetypes/categories), each FLAGGED so its
                       impression is measurable apart from exploited positions.

Randomness (which exploration item lands in a slot) is drawn from a caller-supplied integer
seed (the session watermark), never wall-clock — so a paginated feed is reproducible and the
re-rank is unit-testable.
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional, Sequence

import numpy as np

from app.ranking.centroids import cosine
from app.ranking.types import RankingConfig, ScoredCandidate


def _emb(c: ScoredCandidate) -> Optional[np.ndarray]:
    e = c.features.embedding
    return np.asarray(e, dtype=np.float64) if e is not None else None


def _rel_map(scored: Sequence[ScoredCandidate]) -> Dict[str, float]:
    """Min-max normalise scores into [0, 1] relevance for MMR (scores can be negative once
    fatigue bites). A flat pool maps everything to 1.0."""
    if not scored:
        return {}
    vals = [c.score for c in scored]
    lo, hi = min(vals), max(vals)
    span = hi - lo
    if span <= 0:
        return {c.product_id: 1.0 for c in scored}
    return {c.product_id: (c.score - lo) / span for c in scored}


def _category_shares(cands: Sequence[ScoredCandidate]) -> Dict[str, float]:
    counts: Dict[str, int] = {}
    for c in cands:
        cat = c.features.category or "other"
        counts[cat] = counts.get(cat, 0) + 1
    total = sum(counts.values()) or 1
    return {k: v / total for k, v in counts.items()}


def mmr_calibrated_order(
    scored: Sequence[ScoredCandidate],
    cfg: RankingConfig,
    *,
    target_mix: Optional[Dict[str, float]] = None,
    limit: Optional[int] = None,
) -> List[ScoredCandidate]:
    """Greedy MMR with a category-calibration penalty. Deterministic (tie-break on
    product_id). ``target_mix`` maps category → desired share; over-represented categories
    are damped by ``cfg.category_calibration``."""
    pool = list(scored)
    if not pool:
        return []
    rel = _rel_map(pool)
    target = target_mix or {}
    selected: List[ScoredCandidate] = []
    remaining = pool[:]
    picked_counts: Dict[str, int] = {}
    n_target = limit or len(pool)

    while remaining and len(selected) < n_target:
        best = None
        best_val = None
        picked_total = len(selected) or 1
        for c in remaining:
            r = rel[c.product_id]
            # diversity: similarity to the nearest already-picked product.
            emb_c = _emb(c)
            max_sim = 0.0
            if emb_c is not None:
                for s in selected:
                    emb_s = _emb(s)
                    if emb_s is not None:
                        max_sim = max(max_sim, cosine(emb_c, emb_s))
            # calibration: penalise a category already above its target share.
            cat = c.features.category or "other"
            cur_share = picked_counts.get(cat, 0) / picked_total
            over = max(0.0, cur_share - target.get(cat, 0.0))
            val = cfg.mmr_lambda * r - (1.0 - cfg.mmr_lambda) * max_sim - cfg.category_calibration * over
            # deterministic tie-break: higher val, then lexicographically smaller id.
            if best is None or (val, ) > (best_val, ) or (val == best_val and c.product_id < best.product_id):
                best, best_val = c, val
        selected.append(best)
        cat = best.features.category or "other"
        picked_counts[cat] = picked_counts.get(cat, 0) + 1
        remaining.remove(best)
    return selected


def inject_exploration(
    exploited: Sequence[ScoredCandidate],
    reservoir: Sequence[ScoredCandidate],
    cfg: RankingConfig,
    *,
    seed: int,
    limit: int,
) -> List[ScoredCandidate]:
    """Interleave an exploration slice into the exploited order.

    Every ``step = round(1/ε)`` positions is an exploration slot filled from ``reservoir``
    (lower-ranked candidates NOT in the exploited head), preferring category-NOVEL picks so
    exploration widens the feed rather than echoing it. Each exploration pick has
    ``exploration=True`` set (the flag the impression event carries). ``seed`` (session
    watermark) makes the choice reproducible across pagination."""
    if cfg.exploration_epsilon <= 0 or not reservoir:
        return list(exploited)[:limit]

    step = max(2, round(1.0 / cfg.exploration_epsilon))
    rng = random.Random(seed)
    # Seeded shuffle of the reservoir → stable-but-varied exploration order.
    res = list(reservoir)
    rng.shuffle(res)

    exploited_ids = {c.product_id for c in exploited}
    res = [c for c in res if c.product_id not in exploited_ids]

    exploited_q = list(exploited)
    out: List[ScoredCandidate] = []
    seen_cats: Dict[str, int] = {}
    ei = 0
    while len(out) < limit and (exploited_q or res):
        is_explore_slot = (len(out) + 1) % step == 0
        if is_explore_slot and res:
            # Prefer a reservoir item whose category is under-represented so far.
            pick_idx = 0
            best_novelty = None
            for i, c in enumerate(res):
                cat = c.features.category or "other"
                novelty = -seen_cats.get(cat, 0)  # fewer seen → more novel
                if best_novelty is None or novelty > best_novelty:
                    best_novelty, pick_idx = novelty, i
            c = res.pop(pick_idx)
            c.exploration = True
            c.rerank_reason = "exploration"
            out.append(c)
        elif exploited_q:
            c = exploited_q.pop(0)
            out.append(c)
        elif res:
            c = res.pop(0)
            c.exploration = True
            c.rerank_reason = "exploration"
            out.append(c)
        cat = out[-1].features.category or "other"
        seen_cats[cat] = seen_cats.get(cat, 0) + 1
    return out[:limit]


def rerank(
    scored: Sequence[ScoredCandidate],
    cfg: RankingConfig,
    *,
    target_mix: Optional[Dict[str, float]] = None,
    seed: int = 0,
    limit: int = 24,
) -> List[ScoredCandidate]:
    """Full re-rank: MMR + calibration over the head, then an exploration slice from the
    tail. Returns ``limit`` candidates in feed order (deterministic given ``seed``)."""
    if not scored:
        return []
    # Exploit set: MMR-calibrated top (a bit larger than the page to leave a reservoir).
    head_n = min(len(scored), max(limit, int(limit * 1.5)))
    ordered = mmr_calibrated_order(scored, cfg, target_mix=target_mix, limit=head_n)
    exploited = ordered[:limit]
    reservoir = ordered[limit:] + [c for c in scored if c not in ordered]
    return inject_exploration(exploited, reservoir, cfg, seed=seed, limit=limit)
