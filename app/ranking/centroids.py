"""Taste centroids + the evidence-weighted blend (Wave F2).

Pure vector math over 768-d embeddings (numpy only). No DB. The feature layer hands us
raw vectors; we mean/normalise/blend them. Three centroids feed the ``taste_match`` signal:

  * liked   — mean of the embeddings of items/products the user positively engaged with.
  * closet  — mean of the user's item_embeddings (what they already own).
  * archetype — the onboarding prior. Archetypes store SIGNALS not vectors, and there is
    no image embedder in this stack (item/product embeddings are TEXT embeddings via a
    canonical descriptor). So an archetype's centroid is derived IN THE SAME text space as
    the mean of the stored product-embeddings of catalog products matching the archetype's
    fixed attribute SIGNATURE (see ``ARCHETYPE_SIGNATURES`` / ``archetype_centroid``). This
    keeps it $0-API and self-consistent with the product vectors it will be compared to.
    (A text-descriptor alternative — embedding the archetype's prose look — is documented in
    the report; it needs one embed call per archetype and a shipped asset, so we prefer the
    product-derived route which needs neither.)

The blend weights liked/closet/archetype by α/β/γ, where α grows and γ shrinks with
behavioural evidence — a cold-start user (no likes, no closet) is all-archetype; a user
with a rich closet and likes is taste-driven.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

import numpy as np

from app.ranking.types import RankingConfig

# The six onboarding archetypes (mirrors scripts/gen_taste_deck.py ARCHETYPES keys).
ARCHETYPE_KEYS = ("minimal", "classic", "street", "romantic_boho", "sporty", "edgy")

# Fixed attribute signature per archetype: catalog products matching it define the
# archetype's centroid (mean of their product-embeddings). Deliberately coarse and
# interpretable — a product "matches" if ANY predicate fires (see ``product_matches_archetype``).
# color tokens are matched against color_primary; material/pattern/occasion against their
# fields; formality is a soft band. This is the only place the archetype→garment mapping
# lives, so re-tuning taste priors is one edit here.
ARCHETYPE_SIGNATURES: Dict[str, dict] = {
    "minimal": {
        "colors": {"black", "white", "grey", "gray", "stone", "charcoal", "ivory", "off-white"},
        "max_pattern": True,          # prefers solid / no pattern
        "formality": (2, 4),
    },
    "classic": {
        "colors": {"navy", "white", "beige", "camel", "tan", "grey"},
        "materials": {"wool", "cotton", "twill"},
        "formality": (3, 5),
    },
    "street": {
        "occasions": {"casual", "street", "everyday"},
        "categories": {"outerwear", "top", "bottom"},
        "materials": {"denim", "fleece", "cotton"},
        "formality": (1, 2),
    },
    "romantic_boho": {
        "colors": {"blush", "rust", "olive", "cream", "brown", "floral"},
        "patterns": {"floral", "paisley", "print"},
        "materials": {"linen", "silk", "chiffon"},
        "formality": (2, 3),
    },
    "sporty": {
        "occasions": {"gym", "athletic", "workout", "training", "sport", "running", "active"},
        "materials": {"polyester", "spandex", "lycra", "nylon", "mesh"},
        "formality": (1, 2),
    },
    "edgy": {
        "colors": {"black"},
        "materials": {"leather"},
        "patterns": {"studded", "moto"},
        "formality": (1, 3),
    },
}


def _tok(value) -> str:
    return str(value or "").strip().lower()


def l2_normalize(vec: Sequence[float]) -> Optional[np.ndarray]:
    """Unit-normalise a vector. Returns None for an empty/zero vector."""
    if vec is None:
        return None
    arr = np.asarray(vec, dtype=np.float64)
    if arr.size == 0:
        return None
    norm = float(np.linalg.norm(arr))
    if norm == 0.0 or not math.isfinite(norm):
        return None
    return arr / norm


def mean_vector(vectors: Sequence[Sequence[float]]) -> Optional[np.ndarray]:
    """Mean of a set of vectors, then L2-normalised. None if empty. This is the closet /
    liked centroid: the average taste direction, unit-length for cosine."""
    mat = [np.asarray(v, dtype=np.float64) for v in vectors if v is not None and len(v)]
    if not mat:
        return None
    stacked = np.vstack(mat)
    return l2_normalize(stacked.mean(axis=0))


def cosine(a: Optional[np.ndarray], b: Optional[np.ndarray]) -> float:
    """Cosine similarity of two (ideally unit) vectors. 0.0 if either is missing."""
    if a is None or b is None:
        return 0.0
    va, vb = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    na, nb = float(np.linalg.norm(va)), float(np.linalg.norm(vb))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def blend_weights(
    *,
    has_liked: bool,
    has_closet: bool,
    has_archetype: bool,
    evidence_count: int,
    cfg: RankingConfig,
) -> Dict[str, float]:
    """Evidence-scheduled α/β/γ, renormalised over the centroids that actually exist.

    g = exp(−evidence/scale) ∈ (0, 1]. As behavioural evidence grows (g→0):
      * liked weight α·(1−g) grows 0 → α,
      * archetype weight γ·g shrinks γ → 0,
      * closet weight β is constant (its own presence IS evidence).
    At zero evidence with only an archetype present, that centroid takes the full weight —
    the cold-start user is scored purely on their onboarding prior.
    """
    g = math.exp(-max(0, evidence_count) / max(1e-9, cfg.blend_evidence_scale))
    raw = {
        "liked": cfg.blend_alpha * (1.0 - g) if has_liked else 0.0,
        "closet": cfg.blend_beta if has_closet else 0.0,
        "archetype": cfg.blend_gamma * g if has_archetype else 0.0,
    }
    total = sum(raw.values())
    if total <= 0.0:
        return {"liked": 0.0, "closet": 0.0, "archetype": 0.0}
    return {k: v / total for k, v in raw.items()}


def blend_centroid(
    liked: Optional[np.ndarray],
    closet: Optional[np.ndarray],
    archetype: Optional[np.ndarray],
    *,
    evidence_count: int,
    cfg: RankingConfig,
) -> Optional[np.ndarray]:
    """The taste vector cosine(product, ·) scores against: α·liked ⊕ β·closet ⊕ γ·archetype,
    evidence-weighted (see :func:`blend_weights`) and L2-normalised. None if no centroid
    is available (a user with no likes, no closet, and no archetype — scored taste-neutral)."""
    w = blend_weights(
        has_liked=liked is not None,
        has_closet=closet is not None,
        has_archetype=archetype is not None,
        evidence_count=evidence_count,
        cfg=cfg,
    )
    acc = np.zeros(0)
    parts = [("liked", liked), ("closet", closet), ("archetype", archetype)]
    for name, vec in parts:
        if vec is None or w[name] == 0.0:
            continue
        v = np.asarray(vec, dtype=np.float64)
        acc = v * w[name] if acc.size == 0 else acc + v * w[name]
    if acc.size == 0:
        return None
    return l2_normalize(acc)


# ---------------------------------------------------------------------------
# Archetype → centroid (product-derived, $0 API).
# ---------------------------------------------------------------------------
def product_matches_archetype(product, archetype_key: str) -> bool:
    """True if a product row matches an archetype's SIGNATURE (any predicate fires).

    ``product`` is any object exposing color_primary / material / pattern / category /
    occasions / formality (a ``Product`` ORM row, or the gap job's product adapter)."""
    sig = ARCHETYPE_SIGNATURES.get(archetype_key)
    if not sig:
        return False
    color = _tok(getattr(product, "color_primary", None))
    material = _tok(getattr(product, "material", None))
    pattern = _tok(getattr(product, "pattern", None))
    category = _tok(getattr(product, "category", None))
    occasions = {_tok(o) for o in (getattr(product, "occasions", None) or [])}
    formality = getattr(product, "formality", None)

    if color and color in sig.get("colors", set()):
        return True
    if material and material in sig.get("materials", set()):
        return True
    if pattern and pattern in sig.get("patterns", set()):
        return True
    if category and category in sig.get("categories", set()):
        return True
    if occasions & sig.get("occasions", set()):
        return True
    # Solid-preferring archetypes (minimal): a neutral solid within the formality band.
    if sig.get("max_pattern") and pattern in ("", "solid", "none"):
        lo, hi = sig.get("formality", (1, 5))
        if formality is None or (lo <= int(formality) <= hi):
            return bool(color)  # only credit when we at least know the colour
    return False


def archetype_centroid(
    archetype_key: str,
    products: Sequence,
    embeddings_by_id: Dict[str, Sequence[float]],
) -> Optional[np.ndarray]:
    """Centroid of one archetype = mean product-embedding of matching catalog products.

    ``products`` is a slice of the catalog; ``embeddings_by_id`` maps product id → vector.
    None when too few products match (caller falls back to the global product centroid)."""
    vecs = [
        embeddings_by_id[str(p.id)]
        for p in products
        if str(p.id) in embeddings_by_id and product_matches_archetype(p, archetype_key)
    ]
    if len(vecs) < 3:  # too thin to be a stable prior
        return None
    return mean_vector(vecs)


def archetype_centroid_map(
    products: Sequence,
    embeddings_by_id: Dict[str, Sequence[float]],
) -> Dict[str, np.ndarray]:
    """Build {archetype_key → centroid} over the catalog. Archetypes with too few matches
    are omitted (the caller substitutes the global product centroid for them)."""
    out: Dict[str, np.ndarray] = {}
    for key in ARCHETYPE_KEYS:
        c = archetype_centroid(key, products, embeddings_by_id)
        if c is not None:
            out[key] = c
    return out


def weighted_archetype_centroid(
    archetype_scores: Dict[str, float],
    centroid_map: Dict[str, np.ndarray],
    fallback: Optional[np.ndarray] = None,
) -> Optional[np.ndarray]:
    """Combine a user's per-archetype affinity (from onboarding taste swipes) into one
    prior vector: Σ score·centroid, normalised. ``fallback`` (global product centroid)
    stands in for archetypes with no computed centroid. None if nothing is available."""
    acc = np.zeros(0)
    for key, score in archetype_scores.items():
        if score <= 0.0:
            continue
        vec = centroid_map.get(key, fallback)
        if vec is None:
            continue
        v = np.asarray(vec, dtype=np.float64)
        acc = v * score if acc.size == 0 else acc + v * score
    if acc.size == 0:
        return fallback if fallback is None else l2_normalize(fallback)
    return l2_normalize(acc)
