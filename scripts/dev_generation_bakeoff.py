"""Wave-2 GENERATION BAKE-OFF: our own garment crops -> each provider -> verdicts.

Usage (from project root):
    python -m scripts.dev_generation_bakeoff <email>                    # crops = the user's photo-sourced items
    python -m scripts.dev_generation_bakeoff --dir ./my_crops           # crops = local jpg/png/webp files
    python -m scripts.dev_generation_bakeoff <email> --limit 6          # cap the crop set (default 12)
    python -m scripts.dev_generation_bakeoff <email> --providers flux_kontext,seedream
    python -m scripts.dev_generation_bakeoff <email> --skip-verify      # generate only (no GEMINI key needed)
    python -m scripts.dev_generation_bakeoff <email> --yes              # skip the cost confirmation

WHAT IT DOES
------------
Runs a FIXED set of our own garment crops through every selectable generation
provider (flux_kontext / seedream / nano_banana), verify-scores each candidate
with the two-image reference-vs-generated pass (verify_generated_image), and
prints a comparison table + a per-category provider recommendation. This is
how the per-category default GENERATION_PROVIDER gets picked.

Crop sources: --dir (local files; label = file stem, no attributes) or the
user's photo-ingested items (clothing_items where source_type='photo' AND
image_url set, topped up from ingest_candidates with the same filters, any
status). Neither table has a pattern column (checked app/models.py), so
pattern rides as None — the verify pass treats it as "unknown".

Explicit provider names bypass GENERATION_ENABLED (get_generation_provider(name)
dispatches whenever the provider's key is present — see base.py), so the
bake-off runs against the shipped-disabled seam without flipping any flag.

WHAT IT NEVER DOES
------------------
NO DB writes (read-only queries only), NO storage/bucket writes, NO
product_image_cache writes. Everything lands in the local --out directory:
    out/crops/<idx>_<slug>.<ext>        the source crops (side-by-side eyeballing)
    out/<provider>/<idx>_<slug>.<ext>   each generated candidate
    out/results.json                    per-cell records + aggregates + settings snapshot
    out/report.md                       the same tables + recommendation in markdown
Logs provider/model/verdict only — never prompts, image bytes, or API keys.

FAILURE HONESTY: a skipped verify (disabled / budget / error) is INCONCLUSIVE —
counted separately, never as a pass or a fail. A provider with zero scored
verifies is never recommended; if every verify skipped, the run says the
scoring is inconclusive and recommends nothing.
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

import httpx

from app.core.config import settings
from app.gmail_closet.image_verify import VerifyBudget, verify_generated_image
from app.services.image_generation import (
    GenerationBudget,
    GenerationRequest,
    get_generation_provider,
    list_available_providers,
)

# NOTE: app.db / app.models are imported INSIDE _crops_from_db — a --dir run
# must not require a configured database, and the unit tests import this
# module without one.

DEFAULT_PROVIDERS = "flux_kontext,seedream,nano_banana"

# Rough per-PAIR verify cost for the preview (gemini-2.5-flash-lite, two images
# at MEDIUM media resolution). An estimate for the confirmation gate — the
# billed number comes from Google, not from here.
VERIFY_USD_PER_PAIR = 0.0005

# Provider name -> the settings attribute holding its per-image USD rate.
_PROVIDER_RATE_SETTING = {
    "flux_kontext": "FLUX_KONTEXT_USD_PER_IMAGE",
    "seedream": "SEEDREAM_USD_PER_IMAGE",
    "nano_banana": "NANO_BANANA_USD_PER_IMAGE",
}
# Provider name -> the env var it authenticates with (for the no-key messages).
_PROVIDER_KEY_ENV = {
    "flux_kontext": "BFL_API_KEY",
    "seedream": "FAL_API_KEY",
    "nano_banana": "GEMINI_API_KEY",
}

_EXT_FOR_CTYPE = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_CTYPE_FOR_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


@dataclass
class Crop:
    """One reference garment crop in the fixed bake-off set."""

    label: str
    slug: str
    category: Optional[str]
    color: Optional[str]
    pattern: Optional[str]
    brand: Optional[str]
    image_bytes: bytes
    content_type: str


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested in tests/unit/test_generation_bakeoff.py)
# ---------------------------------------------------------------------------

def slugify(label: Optional[str], max_len: int = 40) -> str:
    """Filesystem-safe slug from an item label: lowercase, runs of non-alnum
    collapse to one dash, trimmed to max_len. Empty -> 'item'."""
    out: List[str] = []
    prev_dash = False
    for ch in (label or "").lower():
        if ch.isalnum():
            out.append(ch)
            prev_dash = False
        elif out and not prev_dash:
            out.append("-")
            prev_dash = True
    slug = "".join(out).strip("-")[:max_len].rstrip("-")
    return slug or "item"


def ext_for(content_type: Optional[str]) -> str:
    """File extension for a (sniffed) image content type. Unknown -> 'img'."""
    ct = (content_type or "").split(";")[0].strip().lower()
    return _EXT_FOR_CTYPE.get(ct, "img")


def cell_filename(idx: int, slug: str, content_type: Optional[str]) -> str:
    """'<idx>_<slug>.<ext>' — the on-disk name for a crop or a candidate."""
    return f"{idx:02d}_{slug}.{ext_for(content_type)}"


def parse_providers(csv: str) -> List[str]:
    """Normalize the --providers CSV: lowercase, trimmed, deduped, order kept."""
    seen: List[str] = []
    for raw in (csv or "").split(","):
        name = raw.strip().lower()
        if name and name not in seen:
            seen.append(name)
    return seen


def estimate_cost(
    n_crops: int,
    provider_names: List[str],
    rates: Dict[str, float],
    include_verify: bool,
) -> dict:
    """Pre-run spend estimate: crops x per-image rate per provider, plus a rough
    verify cost per (crop x provider) pair unless verification is skipped."""
    per_provider = {
        name: round(n_crops * float(rates.get(name, 0.0)), 6) for name in provider_names
    }
    generation = round(sum(per_provider.values()), 6)
    verify = (
        round(n_crops * len(provider_names) * VERIFY_USD_PER_PAIR, 6)
        if include_verify
        else 0.0
    )
    return {
        "per_provider_usd": per_provider,
        "generation_usd": generation,
        "verify_usd": verify,
        "total_usd": round(generation + verify, 6),
    }


def verdict_to_dict(verdict) -> dict:
    """VerifyVerdict -> the JSON-safe verify block stored on a cell."""
    return {
        "skipped": bool(verdict.skipped),
        "matches": bool(verdict.matches),
        "garment_ok": bool(verdict.garment_ok),
        "color_ok": bool(verdict.color_ok),
        "pattern_ok": bool(verdict.pattern_ok),
        "logo_text_ok": bool(verdict.logo_text_ok),
        "score": float(verdict.score),
        "reason": verdict.reason,
        "model": verdict.model,
    }


def make_cell(
    *,
    crop_index: int,
    label: str,
    slug: str,
    category: Optional[str],
    provider: str,
    generated: bool,
    model: Optional[str] = None,
    latency_s: Optional[float] = None,
    cost_usd: Optional[float] = None,
    output_file: Optional[str] = None,
    detail: str = "",
    verify: Optional[dict] = None,
) -> dict:
    """One crop x provider record — results.json, the aggregates and the tests
    all share this shape. verify=None means verification was never attempted
    (--skip-verify, or generation failed); verify['skipped']=True means it was
    attempted but did not run (disabled / budget / error) — inconclusive."""
    return {
        "crop_index": crop_index,
        "label": label,
        "slug": slug,
        "category": category,
        "provider": provider,
        "generated": bool(generated),
        "model": model,
        "latency_s": latency_s,
        "cost_usd": cost_usd,
        "output_file": output_file,
        "detail": detail,
        "verify": verify,
    }


def provider_stats(cells: List[dict]) -> dict:
    """Aggregate one provider's cells.

    Honesty rules: a cell whose verify was skipped (or never attempted) is
    INCONCLUSIVE — excluded from pass/fail and from mean score. pass_rate =
    passes / (scored + generation failures): generation failures count against
    the provider, inconclusive cells never do. pass_rate/mean_score are None
    when NOTHING was scored (no evidence -> no verdict)."""
    attempts = len(cells)
    generated = [c for c in cells if c["generated"]]
    gen_fail = attempts - len(generated)
    scored = [c for c in cells if c["verify"] and not c["verify"]["skipped"]]
    skipped = [c for c in cells if c["verify"] and c["verify"]["skipped"]]
    passes = [c for c in scored if c["verify"]["matches"]]
    fails = [c for c in scored if not c["verify"]["matches"]]
    logo_violations = [c for c in scored if not c["verify"]["logo_text_ok"]]
    pattern_fails = [c for c in scored if not c["verify"]["pattern_ok"]]
    scores = [c["verify"]["score"] for c in scored]
    latencies = [c["latency_s"] for c in generated if c["latency_s"] is not None]
    total_cost = sum(c["cost_usd"] or 0.0 for c in generated)
    return {
        "attempts": attempts,
        "generated": len(generated),
        "gen_fail": gen_fail,
        "scored": len(scored),
        "verified_pass": len(passes),
        "verified_fail": len(fails),
        "verify_skipped": len(skipped),
        "logo_violations": len(logo_violations),
        "pattern_fails": len(pattern_fails),
        "pass_rate": (len(passes) / (len(scored) + gen_fail)) if scored else None,
        "mean_score": statistics.fmean(scores) if scores else None,
        "mean_latency_s": statistics.fmean(latencies) if latencies else None,
        "total_cost_usd": round(total_cost, 6),
    }


def aggregate_providers(
    cells: List[dict], provider_names: Optional[List[str]] = None
) -> Dict[str, dict]:
    """provider -> provider_stats over that provider's cells."""
    if provider_names is None:
        provider_names = list(dict.fromkeys(c["provider"] for c in cells))
    return {
        name: provider_stats([c for c in cells if c["provider"] == name])
        for name in provider_names
    }


def aggregate_categories(
    cells: List[dict], provider_names: Optional[List[str]] = None
) -> Dict[str, Dict[str, dict]]:
    """category -> provider -> provider_stats over that category's cells.
    Crops without a category group under 'unknown'."""
    categories = list(dict.fromkeys((c["category"] or "unknown") for c in cells))
    return {
        cat: aggregate_providers(
            [c for c in cells if (c["category"] or "unknown") == cat], provider_names
        )
        for cat in categories
    }


def recommend_defaults(
    cells: List[dict],
    rates: Dict[str, float],
    provider_names: Optional[List[str]] = None,
) -> dict:
    """Pick a default provider per category + overall.

    Ordering: pass-rate DESC, then mean verify score DESC, then per-image rate
    ASC (cheaper wins), then name (deterministic). Providers with zero SCORED
    verifies are inconclusive and never recommended; a category (or the whole
    run) where every provider is inconclusive gets None."""

    def best(sub_cells: List[dict]) -> Optional[dict]:
        stats = aggregate_providers(sub_cells, provider_names)
        candidates = [(name, s) for name, s in stats.items() if s["scored"] > 0]
        if not candidates:
            return None
        name, s = min(
            candidates,
            key=lambda ns: (
                -(ns[1]["pass_rate"]),
                -(ns[1]["mean_score"] if ns[1]["mean_score"] is not None else -1.0),
                float(rates.get(ns[0], 0.0)),
                ns[0],
            ),
        )
        return {
            "provider": name,
            "pass_rate": s["pass_rate"],
            "mean_score": s["mean_score"],
            "rate_usd_per_image": float(rates.get(name, 0.0)),
            "verified_pass": s["verified_pass"],
            "scored": s["scored"],
        }

    per_category = {
        cat: best([c for c in cells if (c["category"] or "unknown") == cat])
        for cat in dict.fromkeys((c["category"] or "unknown") for c in cells)
    }
    overall = best(cells)
    return {
        "per_category": per_category,
        "overall": overall,
        "inconclusive": overall is None,
    }


# ---------------------------------------------------------------------------
# Rendering (stdout + markdown share the same aggregates)
# ---------------------------------------------------------------------------

def _fmt(value, spec: str, none: str = "—") -> str:
    return format(value, spec) if value is not None else none


def render_provider_table(agg: Dict[str, dict]) -> List[str]:
    header = (
        f"{'PROVIDER':<14}{'ATT':>5}{'GEN':>5}{'GFAIL':>7}{'PASS':>6}{'FAIL':>6}"
        f"{'SKIP':>6}{'LOGO!':>7}{'PAT!':>6}{'P-RATE':>8}{'SCORE':>7}"
        f"{'LAT(s)':>8}{'COST($)':>9}"
    )
    lines = [header, "─" * len(header)]
    for name, s in agg.items():
        lines.append(
            f"{name:<14}{s['attempts']:>5}{s['generated']:>5}{s['gen_fail']:>7}"
            f"{s['verified_pass']:>6}{s['verified_fail']:>6}{s['verify_skipped']:>6}"
            f"{s['logo_violations']:>7}{s['pattern_fails']:>6}"
            f"{_fmt(s['pass_rate'], '.0%'):>8}{_fmt(s['mean_score'], '.2f'):>7}"
            f"{_fmt(s['mean_latency_s'], '.1f'):>8}{s['total_cost_usd']:>9.3f}"
        )
    return lines


def render_category_table(
    cat_agg: Dict[str, Dict[str, dict]], provider_names: List[str]
) -> List[str]:
    header = f"{'CATEGORY':<16}" + "".join(f"{name:>14}" for name in provider_names)
    lines = [header, "─" * len(header)]
    for cat, per_provider in cat_agg.items():
        row = f"{cat[:15]:<16}"
        for name in provider_names:
            s = per_provider.get(name)
            row += f"{_fmt(s['mean_score'] if s else None, '.2f'):>14}"
        lines.append(row)
    return lines


def _rec_line(label: str, best: Optional[dict]) -> str:
    if best is None:
        return f"  {label:<14} -> (inconclusive — no scored verifies)"
    return (
        f"  {label:<14} -> {best['provider']:<13} "
        f"(pass {best['verified_pass']}/{best['scored']} scored, "
        f"pass-rate {_fmt(best['pass_rate'], '.0%')}, "
        f"mean score {_fmt(best['mean_score'], '.2f')}, "
        f"${best['rate_usd_per_image']:.3f}/img)"
    )


def render_recommendations(rec: dict) -> List[str]:
    lines = ["=" * 60, "  RECOMMENDED DEFAULTS", "=" * 60]
    if rec["inconclusive"]:
        lines += [
            "  Scoring INCONCLUSIVE — every verify was skipped (or nothing",
            "  generated). No recommendation. Re-run with verify enabled",
            "  (GMAIL_VERIFY_ENABLED=true + GEMINI_API_KEY, without --skip-verify).",
            "=" * 60,
        ]
        return lines
    for cat, best in rec["per_category"].items():
        lines.append(_rec_line(cat, best))
    lines.append(_rec_line("OVERALL", rec["overall"]))
    lines.append("=" * 60)
    return lines


def render_markdown(
    run_info: dict,
    cost: dict,
    agg: Dict[str, dict],
    cat_agg: Dict[str, Dict[str, dict]],
    rec: dict,
    provider_names: List[str],
) -> str:
    source = run_info["crop_source"]
    source_str = (
        f"--dir {source['dir']}" if "dir" in source else f"photo items of {source['email']}"
    )
    verify_str = (
        "SKIPPED (--skip-verify)"
        if run_info["skip_verify"]
        else f"two-image pass ({settings.GMAIL_VERIFY_MODEL})"
    )
    lines = [
        "# Generation bake-off report",
        "",
        f"- run (UTC): {run_info['timestamp_utc']}",
        f"- crop source: {source_str}",
        f"- crops: {len(run_info['crops'])}",
        f"- providers: {', '.join(provider_names)}",
        f"- verify: {verify_str}",
        f"- estimated spend: ${cost['estimated']['total_usd']:.3f} "
        f"(actual generation spend: ${cost['actual_generation_usd']:.3f})",
        "",
        "## Per-provider results",
        "",
        "| provider | attempts | generated | gen-fail | pass | fail | skipped "
        "| logo! | pattern! | pass-rate | mean score | mean latency (s) | gen cost ($) |",
        "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|",
    ]
    for name, s in agg.items():
        lines.append(
            f"| {name} | {s['attempts']} | {s['generated']} | {s['gen_fail']} "
            f"| {s['verified_pass']} | {s['verified_fail']} | {s['verify_skipped']} "
            f"| {s['logo_violations']} | {s['pattern_fails']} "
            f"| {_fmt(s['pass_rate'], '.0%')} | {_fmt(s['mean_score'], '.2f')} "
            f"| {_fmt(s['mean_latency_s'], '.1f')} | {s['total_cost_usd']:.3f} |"
        )
    lines += [
        "",
        "## Mean verify score by category (non-skipped verifies only)",
        "",
        "| category | " + " | ".join(provider_names) + " |",
        "|---|" + "--:|" * len(provider_names),
    ]
    for cat, per_provider in cat_agg.items():
        cells = " | ".join(
            _fmt(per_provider[name]["mean_score"] if name in per_provider else None, ".2f")
            for name in provider_names
        )
        lines.append(f"| {cat} | {cells} |")
    lines += ["", "## Recommended defaults", ""]
    if rec["inconclusive"]:
        lines.append(
            "Scoring INCONCLUSIVE — every verify was skipped (or nothing generated). "
            "No recommendation."
        )
    else:
        for cat, best in rec["per_category"].items():
            lines.append("- " + _rec_line(cat, best).strip())
        lines.append("- " + _rec_line("OVERALL", rec["overall"]).strip())
    lines.append("")
    return "\n".join(lines)


def settings_snapshot(provider_names: List[str]) -> dict:
    """Config the run depended on — models + rates + verify knobs. NO API keys."""
    models: Dict[str, str] = {}
    for name in provider_names:
        if name == "flux_kontext":
            from app.services.image_generation.flux_kontext import _MODEL as flux_model

            models[name] = flux_model
        elif name == "seedream":
            from app.services.image_generation.seedream import _MODEL as seedream_model

            models[name] = seedream_model
        elif name == "nano_banana":
            # From settings directly — importing nano_banana.py drags google-genai.
            models[name] = settings.NANO_BANANA_MODEL
    return {
        "generation": {
            "models": models,
            "rates_usd_per_image": {
                name: float(getattr(settings, _PROVIDER_RATE_SETTING[name], 0.0))
                for name in provider_names
            },
            "timeout_seconds": float(settings.GENERATION_TIMEOUT_SECONDS),
            "max_per_run": int(settings.GENERATION_MAX_PER_RUN),
        },
        "verify": {
            "enabled": bool(settings.GMAIL_VERIFY_ENABLED),
            "model": settings.GMAIL_VERIFY_MODEL,
            "score_threshold": float(settings.GMAIL_VERIFY_SCORE_THRESHOLD),
            "media_resolution": settings.GENERATION_VERIFY_MEDIA_RESOLUTION,
            "est_usd_per_pair": VERIFY_USD_PER_PAIR,
        },
    }


# ---------------------------------------------------------------------------
# Crop sourcing
# ---------------------------------------------------------------------------

def _crops_from_dir(dir_path: Path, limit: int) -> List[Crop]:
    """Local crop files (jpg/jpeg/png/webp). Label = file stem, no attributes."""
    if not dir_path.is_dir():
        print(f"ERROR: --dir {dir_path} is not a directory")
        sys.exit(1)
    files = sorted(
        p for p in dir_path.iterdir()
        if p.is_file() and p.suffix.lower() in _CTYPE_FOR_EXT
    )
    crops: List[Crop] = []
    for path in files:
        if len(crops) >= limit:
            break
        try:
            data = path.read_bytes()
        except OSError:
            print(f"  skip (unreadable): {path.name}")
            continue
        if not data:
            print(f"  skip (empty file): {path.name}")
            continue
        crops.append(
            Crop(
                label=path.stem,
                slug=slugify(path.stem),
                category=None,
                color=None,
                pattern=None,
                brand=None,
                image_bytes=data,
                content_type=_CTYPE_FOR_EXT[path.suffix.lower()],
            )
        )
    print(f"\nCrop source: --dir {dir_path} ({len(crops)} usable file(s))")
    return crops


def _crops_from_db(email: str, limit: int) -> List[Crop]:
    """The user's own photo-ingested crops: clothing_items (source_type='photo',
    image_url set), topped up from ingest_candidates with the same filters (any
    status). Read-only; downloads each image_url and skips non-200/empty."""
    # Deferred imports: a --dir run must not require a configured database.
    from app.db import SessionLocal
    from app.models import ClothingItem, IngestCandidate, User

    # (label, category, color, brand, url)
    specs: List[Tuple[str, Optional[str], Optional[str], Optional[str], str]] = []
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"ERROR: no user with email {email!r}")
            sys.exit(1)

        items = (
            db.query(ClothingItem)
            .filter(
                ClothingItem.user_id == user.id,
                ClothingItem.source_type == "photo",
                ClothingItem.image_url.isnot(None),
            )
            .order_by(ClothingItem.created_at.asc())
            .all()
        )
        for it in items:
            # No pattern column on clothing_items (checked app/models.py) —
            # pattern stays None; verify treats it as "unknown".
            specs.append((it.name, it.category, it.color_primary, it.brand, it.image_url))

        candidate_count = 0
        if len(specs) < limit:
            candidates = (
                db.query(IngestCandidate)
                .filter(
                    IngestCandidate.user_id == user.id,
                    IngestCandidate.source_type == "photo",
                    IngestCandidate.image_url.isnot(None),
                )
                .order_by(IngestCandidate.created_at.asc())
                .all()
            )
            seen_urls = {url for (_, _, _, _, url) in specs}
            for cand in candidates:
                if cand.image_url in seen_urls:
                    continue
                specs.append(
                    (cand.name or "item", cand.category, cand.color, cand.brand, cand.image_url)
                )
                candidate_count += 1

        print(f"\nUser:    {email}")
        print(f"user_id: {user.id}")
        print(
            f"Photo crops found: {len(specs)} "
            f"(clothing_items={len(items)}, +ingest_candidates={candidate_count})"
        )
    finally:
        db.close()

    crops: List[Crop] = []
    with httpx.Client(timeout=20.0, follow_redirects=True) as http:
        for label, category, color, brand, url in specs:
            if len(crops) >= limit:
                break
            try:
                resp = http.get(url)
            except Exception as exc:
                print(f"  skip (download error {type(exc).__name__}): {slugify(label)}")
                continue
            if resp.status_code != 200 or not resp.content:
                print(f"  skip (HTTP {resp.status_code} / empty): {slugify(label)}")
                continue
            ctype = (resp.headers.get("content-type") or "").split(";")[0].strip()
            crops.append(
                Crop(
                    label=label,
                    slug=slugify(label),
                    category=category,
                    color=color,
                    pattern=None,
                    brand=brand,
                    image_bytes=resp.content,
                    content_type=ctype or "image/jpeg",
                )
            )
    return crops


# ---------------------------------------------------------------------------
# The matrix run
# ---------------------------------------------------------------------------

def _progress_line(cell: dict) -> str:
    """One redaction-safe line per crop x provider cell (never bytes/prompts)."""
    tag = f"{cell['crop_index']:02d}_{cell['slug']}"
    if not cell["generated"]:
        return (
            f"  [{cell['provider']:<12}] {tag:<44} gen=FAIL "
            f"({cell['detail'] or 'no result'})"
        )
    v = cell["verify"]
    if v is None:
        verify_label = "verify=—"
    elif v["skipped"]:
        verify_label = "verify=skipped"
    else:
        verify_label = f"verify={'PASS' if v['matches'] else 'FAIL'} score={v['score']:.2f}"
    latency = f"lat={cell['latency_s']:.1f}s" if cell["latency_s"] is not None else "lat=—"
    cost = f"cost=${cell['cost_usd']:.3f}" if cell["cost_usd"] is not None else "cost=—"
    return f"  [{cell['provider']:<12}] {tag:<44} gen=ok {verify_label} {latency} {cost}"


def _run_matrix(
    crops: List[Crop],
    provider_names: List[str],
    out_dir: Path,
    skip_verify: bool,
) -> List[dict]:
    """crop x provider: generate -> save candidate -> verify. Returns all cells."""
    cells: List[dict] = []
    # Shared verify cap across the whole matrix (skipped cells report honestly).
    verify_budget = VerifyBudget(
        min(len(crops) * len(provider_names), settings.GMAIL_VERIFY_MAX_PER_RUN)
    )

    for name in provider_names:
        provider = get_generation_provider(name)
        if getattr(provider, "name", "null") == "null":
            # Availability was pre-checked; belt-and-braces so a Null column
            # can never silently masquerade as a scored provider.
            print(f"  [{name}] resolved to the null provider — recording column as failed")
        provider_dir = out_dir / name
        provider_dir.mkdir(parents=True, exist_ok=True)
        # Per-provider generation cap, sized to the crop set (and never above
        # the per-run guard GENERATION_MAX_PER_RUN).
        gen_budget = GenerationBudget(min(len(crops), settings.GENERATION_MAX_PER_RUN))

        for i, crop in enumerate(crops):
            base = dict(
                crop_index=i, label=crop.label, slug=crop.slug,
                category=crop.category, provider=name,
            )
            if not gen_budget.take():
                cell = make_cell(generated=False, detail="generation budget exhausted", **base)
                cells.append(cell)
                print(_progress_line(cell))
                continue

            result = provider.generate(
                GenerationRequest(
                    image_bytes=crop.image_bytes,
                    content_type=crop.content_type,
                    name=crop.label,
                    category=crop.category,
                    color=crop.color,
                    pattern=crop.pattern,
                    brand=crop.brand,
                )
            )
            if result is None:
                cell = make_cell(generated=False, detail="generation failed", **base)
                cells.append(cell)
                print(_progress_line(cell))
                continue

            out_file = provider_dir / cell_filename(i, crop.slug, result.content_type)
            out_file.write_bytes(result.image_bytes)

            verify = None
            if not skip_verify:
                verdict = verify_generated_image(
                    reference_bytes=crop.image_bytes,
                    reference_content_type=crop.content_type,
                    candidate_bytes=result.image_bytes,
                    candidate_content_type=result.content_type,
                    category=crop.category,
                    color=crop.color,
                    pattern=crop.pattern,
                    name=crop.label,
                    budget=verify_budget,
                )
                verify = verdict_to_dict(verdict)

            cell = make_cell(
                generated=True,
                model=result.model,
                latency_s=round(float(result.latency_s), 2),
                cost_usd=result.cost_usd,
                output_file=str(out_file.relative_to(out_dir)),
                detail=result.detail,
                verify=verify,
                **base,
            )
            cells.append(cell)
            print(_progress_line(cell))
    return cells


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m scripts.dev_generation_bakeoff")
    parser.add_argument(
        "email", nargs="?", default=None,
        help="User whose photo crops feed the bake-off (clothing_items.source_type='photo').",
    )
    parser.add_argument(
        "--dir", dest="crop_dir", default=None,
        help="Local directory of crop files (jpg/jpeg/png/webp). Overrides the email query.",
    )
    parser.add_argument("--limit", type=int, default=12, help="Max crops in the set (default 12).")
    parser.add_argument(
        "--providers", default=DEFAULT_PROVIDERS,
        help=f"CSV of providers to compare (default: {DEFAULT_PROVIDERS}).",
    )
    parser.add_argument(
        "--out", default=None,
        help="Output directory (default: ./bakeoff_out/<UTC yyyymmdd-HHMMSS>).",
    )
    parser.add_argument(
        "--skip-verify", action="store_true",
        help="Generate only — skip the verify pass (for when GEMINI_API_KEY is absent).",
    )
    parser.add_argument("--yes", action="store_true", help="Skip the cost confirmation prompt.")
    args = parser.parse_args()

    if not args.email and not args.crop_dir:
        parser.error("provide a user email and/or --dir (need at least one crop source)")
    if args.limit < 1:
        parser.error("--limit must be >= 1")
    requested = parse_providers(args.providers)
    if not requested:
        parser.error("--providers is empty")

    try:
        # ---- provider availability -------------------------------------------
        available = list_available_providers()
        provider_names: List[str] = []
        print("\nProviders requested:")
        for name in requested:
            if name not in available:
                print(f"  {name}: SKIPPED (unknown provider — known: {', '.join(available)})")
            elif not available[name]:
                print(f"  {name}: SKIPPED (no key — set {_PROVIDER_KEY_ENV[name]})")
            else:
                print(f"  {name}: ok")
                provider_names.append(name)
        if not provider_names:
            print("\nERROR: no requested provider has an API key configured.")
            print("       Set BFL_API_KEY (flux_kontext), FAL_API_KEY (seedream) and/or")
            print("       GEMINI_API_KEY (nano_banana), then re-run.")
            sys.exit(1)

        # ---- verify guard ------------------------------------------------------
        if not args.skip_verify and (
            not settings.GMAIL_VERIFY_ENABLED or not settings.GEMINI_API_KEY
        ):
            print("\nERROR: the verify pass needs GMAIL_VERIFY_ENABLED=true and GEMINI_API_KEY.")
            print("       Fix the env, or re-run with --skip-verify (generate only — no scoring,")
            print("       no recommendation).")
            sys.exit(1)

        # ---- 1. fixed crop set -------------------------------------------------
        if args.crop_dir:
            crops = _crops_from_dir(Path(args.crop_dir), args.limit)
        else:
            crops = _crops_from_db(args.email.strip(), args.limit)
        if not crops:
            source = f"--dir {args.crop_dir}" if args.crop_dir else f"photo items of {args.email!r}"
            print(f"\nERROR: no usable crops from {source}.")
            print("       DB source needs clothing_items/ingest_candidates with "
                  "source_type='photo' and an image_url;")
            print("       --dir needs readable .jpg/.jpeg/.png/.webp files.")
            sys.exit(1)
        total_cells = len(crops) * len(provider_names)
        print(f"\nMatrix: {len(crops)} crop(s) x {len(provider_names)} provider(s) "
              f"= {total_cells} generation call(s)")

        # ---- 2. cost preview + confirmation gate --------------------------------
        rates = {
            name: float(getattr(settings, _PROVIDER_RATE_SETTING[name], 0.0))
            for name in provider_names
        }
        cost_preview = estimate_cost(
            len(crops), provider_names, rates, include_verify=not args.skip_verify
        )
        print("\nESTIMATED SPEND")
        for name in provider_names:
            print(f"  {name:<14} {len(crops):>3} img  x ${rates[name]:.3f} "
                  f"= ${cost_preview['per_provider_usd'][name]:.3f}")
        if not args.skip_verify:
            print(f"  {'verify':<14} {total_cells:>3} pair x ${VERIFY_USD_PER_PAIR:.4f} "
                  f"= ${cost_preview['verify_usd']:.3f} (rough)")
        print(f"  {'TOTAL':<14} ~${cost_preview['total_usd']:.3f}")
        if not args.yes:
            try:
                answer = input("\nProceed with the paid run? [y/N] ").strip().lower()
            except EOFError:
                answer = ""
            if answer not in ("y", "yes"):
                print("Aborted — nothing generated, nothing spent.")
                sys.exit(1)

        # ---- 3. output directory (the ONLY place this script writes) ------------
        out_dir = (
            Path(args.out)
            if args.out
            else Path("bakeoff_out") / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        )
        crops_dir = out_dir / "crops"
        crops_dir.mkdir(parents=True, exist_ok=True)
        for i, crop in enumerate(crops):
            (crops_dir / cell_filename(i, crop.slug, crop.content_type)).write_bytes(
                crop.image_bytes
            )
        print(f"\nOutput dir: {out_dir}  (source crops copied to crops/ for side-by-side)\n")

        # ---- 4. the matrix -------------------------------------------------------
        cells = _run_matrix(crops, provider_names, out_dir, args.skip_verify)

        # ---- 5. report -------------------------------------------------------------
        agg = aggregate_providers(cells, provider_names)
        cat_agg = aggregate_categories(cells, provider_names)
        rec = recommend_defaults(cells, rates, provider_names)

        print("\nPER-PROVIDER RESULTS")
        for line in render_provider_table(agg):
            print(line)
        print("\nMEAN VERIFY SCORE BY CATEGORY (non-skipped verifies only)")
        for line in render_category_table(cat_agg, provider_names):
            print(line)
        print()
        for line in render_recommendations(rec):
            print(line)

        actual_gen_cost = round(sum(s["total_cost_usd"] for s in agg.values()), 6)
        scored_total = sum(s["scored"] for s in agg.values())
        skipped_total = sum(s["verify_skipped"] for s in agg.values())

        run_info = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "crop_source": {"dir": args.crop_dir} if args.crop_dir else {"email": args.email},
            "limit": args.limit,
            "providers_requested": requested,
            "providers_run": provider_names,
            "skip_verify": bool(args.skip_verify),
            "crops": [
                {
                    "index": i,
                    "label": c.label,
                    "slug": c.slug,
                    "category": c.category,
                    "color": c.color,
                    "pattern": c.pattern,
                    "brand": c.brand,
                    "content_type": c.content_type,
                    "bytes": len(c.image_bytes),
                    "file": f"crops/{cell_filename(i, c.slug, c.content_type)}",
                }
                for i, c in enumerate(crops)
            ],
        }
        cost_block = {
            "estimated": cost_preview,
            "actual_generation_usd": actual_gen_cost,
            "estimated_verify_usd": round(scored_total * VERIFY_USD_PER_PAIR, 6),
        }
        results = {
            "run": run_info,
            "settings": settings_snapshot(provider_names),  # models + rates, NO api keys
            "cost": cost_block,
            "cells": cells,
            "provider_aggregates": agg,
            "category_aggregates": cat_agg,
            "recommendations": rec,
        }
        (out_dir / "results.json").write_text(json.dumps(results, indent=2, default=str))
        (out_dir / "report.md").write_text(
            render_markdown(run_info, cost_block, agg, cat_agg, rec, provider_names)
        )

        # ---- summary ---------------------------------------------------------------
        print("\n" + "=" * 60)
        print("  BAKE-OFF SUMMARY")
        print("=" * 60)
        print(f"  crops:                 {len(crops)}")
        print(f"  providers run:         {', '.join(provider_names)}")
        print(f"  cells (crop x prov):   {len(cells)}")
        print(f"  generated:             {sum(s['generated'] for s in agg.values())}")
        print(f"  generation failures:   {sum(s['gen_fail'] for s in agg.values())}")
        if args.skip_verify:
            print("  verify:                SKIPPED (--skip-verify) — scoring inconclusive")
        else:
            print(f"  verified pass:         {sum(s['verified_pass'] for s in agg.values())}")
            print(f"  verified fail:         {sum(s['verified_fail'] for s in agg.values())}")
            print(f"  verify skipped:        {skipped_total} (inconclusive — not pass, not fail)")
            print(f"  logo violations:       {sum(s['logo_violations'] for s in agg.values())}")
        print(f"  generation spend:      ${actual_gen_cost:.3f}")
        if scored_total:
            print(f"  verify spend (est):    ${scored_total * VERIFY_USD_PER_PAIR:.4f}")
        print(f"  output:                {out_dir}/ (results.json, report.md)")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)


if __name__ == "__main__":
    main()
