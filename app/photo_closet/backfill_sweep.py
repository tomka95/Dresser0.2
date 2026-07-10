"""Photo-seam Phase 6 — THE invariant backfill sweep.

After Phases 1-5 every NEW write satisfies the universal image invariant. This sweep
brings every EXISTING row into compliance — idempotent, resumable, cost-bounded:

  B1  ready + person!=person_free rows (pre-P1 leak): re-validated like B5; on a full
      v2 pass the state is REPAIRED (person_free + marker, stays ready); on a fail the
      row is knocked out of 'ready' and regenerated through the shared seam.
  B2  stranded budget-residue (staged/NULL and staged/pending_retry shapes nothing
      re-selects): normalized to pending_retry + image_pending (heal-eligible). Free.
  B3  ready/terminal photo rows still holding a raw photo_items/ crop (pre-P5): the
      P5 purge applied retroactively. Runs AFTER re-validation (the crop is the best
      regeneration reference for a failing card).
  B4  gmail frozen rows (staged/unknown, never ran the completed pipeline): driven
      through run_image_fill (person-detection -> generation-to-completion -> settle).
  B5  EVERY displayable image whose invariant_checked_at is NULL (pre-verify-v2
      'ready' images): re-checked against the v2 hard gates (person + extra-garment +
      off-white + framing + garment/color match). Pass -> marker stamped. Fail ->
      knocked out of display (fail-closed) and regenerated INLINE through the shared
      core using the failing image as the identity reference; restored only on a full
      pass; attempt ceiling -> terminal 'failed', never a violating image left shown.

IDEMPOTENT + RESUMABLE: invariant_checked_at is the resume marker (validated rows are
never re-billed); regeneration honors generation_attempts + the shared call budget;
every mutation commits per row. DRY-RUN FIRST: classify() is read-only.

SECURITY/PRIVACY: ids + counts only in logs; verify/generation through the same
SSRF-guarded, budget-capped seams as live traffic; unbranded items stay out of the
shared cache (P1 brand-gating in the seam itself).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.gmail_closet.image_verify import VerifyBudget, verify_image
from app.models import ClothingItem, IngestCandidate
from app.photo_closet.generation_service import (
    _download_bytes,
    _maybe_promote_card,
    _next_failure_status,
    _now_utc,
    _purge_crop_reference,
    _stamp_candidate_card_ready,
    _storage_from_env,
)
from app.platform.usage import UsageAccumulator
from app.services.image_generation.base import GenerationBudget
from app.services.image_generation.generate_core import generate_from_reference_bytes
from app.services.readiness import advance, mark_candidate_ready, tags_ready

logger = logging.getLogger(__name__)

_PHOTOISH = ("photo", "manual")


@dataclass
class SweepReport:
    """Redaction-safe classification + execution counters (ids/counts only)."""
    # --- dry-run classification ---------------------------------------------
    b1_ready_person_violations: int = 0
    b2_stranded_residue: int = 0
    b3_ready_rows_holding_crops: int = 0
    b4_gmail_frozen: int = 0
    b5_unvalidated_candidates: int = 0
    b5_unvalidated_items: int = 0
    b5_items_no_image: int = 0         # subset of b5_unvalidated_items: image_url NULL
    b5_items_suspected_non_clothing: int = 0  # subset: name/category smells non-clothing
    projected_verify_calls: int = 0
    projected_regens_upper: int = 0    # worst case: every unvalidated image needs a regen
    # --- execution ------------------------------------------------------------
    executed: bool = False
    revalidated_pass: int = 0
    revalidated_fail: int = 0
    regenerated: int = 0               # failing/missing images replaced by a compliant card
    demoted: int = 0                   # knocked out of display, left heal-eligible
    terminal_failed: int = 0           # attempt ceiling burned -> 'failed'
    verify_skipped: int = 0            # budget/error -> marker left NULL (resume target)
    residue_normalized: int = 0
    crops_purged: int = 0
    quarantined: List[dict] = field(default_factory=list)  # [{id, name, category}, ...]
    budget_stopped: bool = False
    errors: int = 0


# ---------------------------------------------------------------------------
# Classification (read-only, the dry run)
# ---------------------------------------------------------------------------

def _b1_query(db: Session):
    return db.query(IngestCandidate).filter(
        IngestCandidate.pipeline_state == "ready",
        IngestCandidate.person_status != "person_free",
    )


def _b2_query(db: Session):
    # No status filter: pre-P1 CONFIRMED rows sit stranded in this shape too (their
    # items are live; the candidate row's state is normalized for hygiene so no query
    # can ever mistake it for in-flight work).
    return db.query(IngestCandidate).filter(
        IngestCandidate.source_type.in_(_PHOTOISH),
        IngestCandidate.pipeline_state == "staged",
        IngestCandidate.generated_image_url.is_(None),
        IngestCandidate.image_url.isnot(None),
        or_(
            IngestCandidate.generation_status.is_(None),
            IngestCandidate.generation_status == "pending_retry",
        ),
        IngestCandidate.generation_attempts < settings.GENERATION_MAX_ATTEMPTS,
    )


def _b3_query(db: Session):
    # Terminal rows AND already-confirmed ('accepted') rows: in both cases the crop's
    # generation-reference purpose is over — a person-containing source must not linger.
    return db.query(IngestCandidate).filter(
        IngestCandidate.source_type.in_(_PHOTOISH),
        IngestCandidate.image_url.like("%/photo_items/%"),
        or_(
            IngestCandidate.generation_status.in_(("ready", "failed")),
            IngestCandidate.pipeline_state.in_(("ready", "failed")),
            IngestCandidate.status == "accepted",
        ),
    )


def _b4_query(db: Session):
    return db.query(IngestCandidate).filter(
        IngestCandidate.status == "pending",
        IngestCandidate.source_type == "gmail",
        IngestCandidate.pipeline_state.notin_(("ready", "failed")),
    )


def _b5_candidates_query(db: Session):
    return db.query(IngestCandidate).filter(
        IngestCandidate.invariant_checked_at.is_(None),
        or_(
            IngestCandidate.generated_image_url.isnot(None),
            # gmail candidates with a resolved image (their display card)
            (IngestCandidate.source_type == "gmail")
            & IngestCandidate.image_url.isnot(None)
            & (IngestCandidate.image_status == "resolved"),
        ),
    )


def _b5_items_query(db: Session):
    """B5b (whole-table, Photo-seam Phase 6b): EVERY clothing_item lacking the
    invariant marker — no displayability filter, no image_url filter. The original
    query required the row to ALREADY be displayable (person_free / generation
    'ready'), which silently excluded pre-rebuild rows stuck at person_status=
    'unknown' / generation_status=NULL — exactly the rows most likely to violate the
    invariant (imageless, or an unverified retailer photo). archived_at excludes
    already-quarantined rows so quarantine is idempotent."""
    return db.query(ClothingItem).filter(
        ClothingItem.invariant_checked_at.is_(None),
        ClothingItem.archived_at.is_(None),
    )


# Non-clothing name smell test (Phase 6b): category alone can't discriminate — a
# lunch bag and a scarf are both filed under 'accessory'. Deliberately narrow and
# conservative: only 'accessory'-categoried rows are checked (real clothing
# categories — top/bottom/dress/outerwear/shoes — are never auto-quarantined), and
# only on an explicit non-wearable keyword hit. A miss here just means a normal B5
# regen attempt on a junk row (wasted cost, never wrong); a false positive would
# hide a real accessory, which is why the keyword list stays narrow and literal.
_NON_CLOTHING_KEYWORDS = (
    "lunch bag", "lunch box", "handbag", "tote bag", "tableware", "food storage",
    "hairpin", "hair clip", "hair accessory", "hair barrette", "claw clip",
    "phone case", "water bottle", "yoga mat", "cutlery", "kitchen", "home decor",
    "storage box", "makeup bag", "cosmetic bag", "pencil case", "stationery",
)


def _looks_like_non_clothing(name: Optional[str], category: Optional[str]) -> bool:
    if (category or "").strip().lower() != "accessory":
        return False
    n = (name or "").lower()
    return any(kw in n for kw in _NON_CLOTHING_KEYWORDS)


def classify(db: Session) -> SweepReport:
    """Read-only bucket classification + projected worst-case cost."""
    r = SweepReport()
    r.b1_ready_person_violations = _b1_query(db).count()
    r.b2_stranded_residue = _b2_query(db).count()
    r.b3_ready_rows_holding_crops = _b3_query(db).count()
    r.b4_gmail_frozen = _b4_query(db).count()
    r.b5_unvalidated_candidates = _b5_candidates_query(db).count()
    item_rows = _b5_items_query(db).all()
    r.b5_unvalidated_items = len(item_rows)
    r.b5_items_no_image = sum(1 for it in item_rows if not it.image_url)
    r.b5_items_suspected_non_clothing = sum(
        1 for it in item_rows if _looks_like_non_clothing(it.name, it.category)
    )
    # Verify billing only applies to rows that HAVE an image to check; imageless
    # rows skip straight to generation (no existing image to verify), and
    # suspected-non-clothing rows are quarantined for free (no billing at all).
    billable_items = r.b5_unvalidated_items - r.b5_items_no_image - r.b5_items_suspected_non_clothing
    r.projected_verify_calls = r.b5_unvalidated_candidates + billable_items
    # Worst case every unvalidated/imageless clothing row needs a regen (a full
    # 2-rung ladder each); B4's gmail fill adds its own (cache-first, capped) work.
    r.projected_regens_upper = (
        r.b5_unvalidated_candidates + r.b5_unvalidated_items - r.b5_items_suspected_non_clothing
    )
    return r


# ---------------------------------------------------------------------------
# The v2 invariant check for ONE stored image (bytes already fetched)
# ---------------------------------------------------------------------------

def _invariant_ok(verdict) -> bool:
    return bool(
        verdict.matches
        and not verdict.person_present
        and not verdict.extra_items_present
        and verdict.background_offwhite_ok
        and verdict.framing_ok
    )


def _bump_attempts(row) -> None:
    row.generation_attempts = (row.generation_attempts or 0) + 1
    row.generation_status = _next_failure_status(row.generation_attempts)


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------

def run_sweep(
    db: Session,
    *,
    execute: bool = False,
    gen_budget: Optional[GenerationBudget] = None,
    verify_budget: Optional[VerifyBudget] = None,
    storage_client=None,
    run_gmail_fill: bool = True,
) -> SweepReport:
    """Classify, then (execute=True) bring every bucket into compliance. Never raises."""
    report = classify(db)
    if not execute:
        return report
    report.executed = True

    if storage_client is None:
        storage_client = _storage_from_env()
    if gen_budget is None:
        gen_budget = GenerationBudget(settings.GENERATION_MAX_PER_RUN)
    if verify_budget is None:
        verify_budget = VerifyBudget(settings.GMAIL_VERIFY_MAX_PER_RUN)
    usage = UsageAccumulator()

    try:
        _normalize_residue(db, report)                       # B2 (free)
        if run_gmail_fill:
            _run_gmail_fill(db, report, gen_budget)          # B4 (own budgets inside)
        _revalidate_candidates(                              # B1 + B5 (candidates)
            db, report, storage_client, gen_budget, verify_budget, usage,
        )
        _revalidate_items(                                   # B5 (items)
            db, report, storage_client, gen_budget, verify_budget, usage,
        )
        _purge_legacy_crops(db, report, storage_client)      # B3 (after revalidation)
    except Exception as exc:  # the sweep is best-effort per row; never explode
        logger.error("backfill sweep error: %s: %s", type(exc).__name__, exc)
        report.errors += 1
        try:
            db.rollback()
        except Exception:
            pass

    logger.info(
        "backfill sweep done: pass=%d fail=%d regen=%d demoted=%d terminal=%d "
        "skipped=%d residue=%d purged=%d budget_stopped=%s errors=%d",
        report.revalidated_pass, report.revalidated_fail, report.regenerated,
        report.demoted, report.terminal_failed, report.verify_skipped,
        report.residue_normalized, report.crops_purged, report.budget_stopped,
        report.errors,
    )
    return report


def _normalize_residue(db: Session, report: SweepReport) -> None:
    """B2: stranded staged/NULL + staged/pending_retry residue -> heal-eligible."""
    for c in _b2_query(db).all():
        c.generation_status = "pending_retry"
        advance(c, "image_pending")
        report.residue_normalized += 1
    db.commit()


def _run_gmail_fill(db: Session, report: SweepReport, gen_budget: GenerationBudget) -> None:
    """B4: drive frozen gmail candidates through the completed pipeline, per user.

    run_image_fill owns its budgets and caps candidates per pass, so a big frozen
    batch drains over MULTIPLE passes — loop (bounded) while a pass makes progress.
    A user whose pass moves nothing (no token / nothing actionable) stops immediately."""
    from app.gmail_closet.image_fill_service import run_image_fill

    user_ids = [row[0] for row in _b4_query(db).with_entities(IngestCandidate.user_id).distinct()]
    for uid in user_ids:
        for _pass in range(6):
            try:
                stats = run_image_fill(uid, db)
            except Exception as exc:
                logger.warning("sweep gmail fill user=%s failed (%s)", uid, type(exc).__name__)
                report.errors += 1
                break
            progress = (
                stats.ready + stats.failed + stats.cache_filled + stats.slow_filled
                + stats.generated + stats.exhausted + stats.person_checked
            )
            logger.info(
                "sweep gmail fill user=%s pass=%d progress=%d ready=%d failed=%d",
                uid, _pass + 1, progress, stats.ready, stats.failed,
            )
            if progress == 0:
                break


def _revalidate_candidates(
    db: Session, report: SweepReport, storage_client, gen_budget, verify_budget, usage,
) -> None:
    """B1 + B5 for candidates: verify each unvalidated display image against v2;
    repair/stamp on pass, demote + regenerate inline on fail. Per-row commits."""
    rows: List[IngestCandidate] = _b5_candidates_query(db).all()
    for cand in rows:
        photoish = (cand.source_type or "gmail") in _PHOTOISH
        card_url = cand.generated_image_url if photoish else cand.image_url
        if not card_url:
            continue
        dl = _download_bytes(card_url)
        if dl is None:
            report.verify_skipped += 1
            continue  # transient; marker stays NULL -> next run retries
        img_bytes, img_ct = dl
        verdict = verify_image(
            image_bytes=img_bytes, content_type=img_ct,
            category=cand.category, color=cand.color, name=cand.name,
            budget=verify_budget, usage=usage,
        )
        if getattr(verdict, "skipped", False):
            report.verify_skipped += 1
            report.budget_stopped = report.budget_stopped or "budget" in (verdict.reason or "")
            continue

        if _invariant_ok(verdict):
            # PASS: stamp; repair a pre-P1 ready+person state to the truth (the card
            # itself is affirmatively person-free).
            cand.invariant_checked_at = _now_utc()
            if cand.pipeline_state == "ready" and cand.person_status != "person_free":
                cand.person_status = "person_free"
            report.revalidated_pass += 1
            db.commit()
            continue

        # FAIL: fail-closed — knock out of display/'ready', regenerate inline using
        # the failing image as the identity reference.
        report.revalidated_fail += 1
        if photoish:
            old_card = cand.generated_image_url
            if not cand.image_url:
                cand.image_url = old_card  # keep an identity reference for the seam
            cand.generated_image_url = None
        cand.generation_status = "pending_retry"
        cand.pipeline_state = "image_pending"
        if verdict.person_present:
            cand.person_status = "person_present"
        db.commit()
        report.demoted += 1

        if gen_budget.remaining <= 0:
            report.budget_stopped = True
            continue
        g = generate_from_reference_bytes(
            reference_bytes=img_bytes, reference_content_type=img_ct,
            name=cand.name, category=cand.category, color=cand.color,
            brand=cand.brand, pattern=None,
            storage_client=storage_client, user_id=cand.user_id,
            gen_budget=gen_budget, verify_budget=verify_budget, usage=usage,
        )
        if g.outcome == "ready" and g.url:
            if photoish:
                _stamp_candidate_card_ready(db, cand, g.url, storage_client=storage_client)
            else:
                cand.image_url = g.url
                cand.image_status = "resolved"
                cand.person_status = "person_free"
                cand.invariant_checked_at = _now_utc()
                advance(cand, "verified_clean")
                if tags_ready(cand):
                    mark_candidate_ready(cand)
            db.commit()
            _maybe_promote_card(
                brand=cand.brand, name=cand.name, color=cand.color,
                url=g.url, content_sha256=g.content_sha256, verify_score=g.verify_score,
            )
            report.regenerated += 1
        elif g.outcome == "budget":
            report.budget_stopped = True
        else:
            _bump_attempts(cand)
            if cand.generation_status == "failed":
                cand.pipeline_state = "failed"
                if not photoish:
                    # gmail terminal: the non-compliant image must never display.
                    cand.image_url = None
                    cand.image_status = "placeholder"
                report.terminal_failed += 1
            db.commit()


def _quarantine_item(db: Session, it: ClothingItem, report: SweepReport) -> None:
    """Quarantine (never auto-delete): archived_at hides it from every read path
    (ranking/features, ranking/feed, stylist retrieval, todays_look, and — as of the
    Phase 6b list_closet_items fix — the closet grid itself). invariant_checked_at
    is stamped too so the row converges out of every future sweep. Reversible: an
    operator un-archives (archived_at=NULL) to restore a false positive."""
    it.archived_at = _now_utc()
    it.invariant_checked_at = _now_utc()
    report.quarantined.append({
        "id": str(it.id), "name": it.name, "category": it.category,
    })
    logger.info("quarantined non-clothing item=%s category=%s", it.id, it.category)
    db.commit()


def _revalidate_items(
    db: Session, report: SweepReport, storage_client, gen_budget, verify_budget, usage,
) -> None:
    """B5 for confirmed items (Phase 6b: whole-table — see _b5_items_query).

    Three branches per unvalidated row:
      * suspected non-clothing (accessory + a junk-keyword name) -> QUARANTINE, no
        billing, never imaged.
      * image_url IS NULL (rule (1) violation: no image at all) -> t2i straight to
        a compliant card (nothing existing to verify).
      * has an image -> the original re-validate flow: verify-v2, pass -> stamp,
        fail -> mask (generation_status='pending_retry', hides it for EVERY source)
        + regenerate inline from its own bytes.
    Ceiling burned in any generation path -> terminal 'failed' (masked forever,
    never a violating/imageless-but-displayable row)."""
    rows: List[ClothingItem] = _b5_items_query(db).all()
    for it in rows:
        if _looks_like_non_clothing(it.name, it.category):
            _quarantine_item(db, it, report)
            continue

        if not it.image_url:
            # Rule (1): no image at all. Nothing to verify — go straight to t2i.
            if gen_budget.remaining <= 0:
                report.budget_stopped = True
                continue
            from app.services.image_generation.generate_core import generate_from_text

            g = generate_from_text(
                name=it.name, category=it.category, color=it.color_primary,
                brand=it.brand,
                storage_client=storage_client, user_id=it.user_id,
                gen_budget=gen_budget, verify_budget=verify_budget, usage=usage,
            )
            if g.outcome == "ready" and g.url:
                it.image_url = g.url
                it.generation_status = "ready"
                it.generation_attempts = 0
                it.person_status = "person_free"
                it.invariant_checked_at = _now_utc()
                db.commit()
                _maybe_promote_card(
                    brand=it.brand, name=it.name, color=it.color_primary,
                    url=g.url, content_sha256=g.content_sha256, verify_score=g.verify_score,
                )
                report.regenerated += 1
            elif g.outcome == "budget":
                report.budget_stopped = True
            else:
                _bump_attempts(it)
                if it.generation_status == "failed":
                    # Fail-closed: still imageless, but generation_status='failed'
                    # keeps display_image_url masked — never imageless-and-shown.
                    # Stamped checked so this terminal row stops being re-selected;
                    # it remains a real (masked) rule-(1) gap, reported separately.
                    it.invariant_checked_at = _now_utc()
                    report.terminal_failed += 1
                db.commit()
            continue

        dl = _download_bytes(it.image_url)
        if dl is None:
            report.verify_skipped += 1
            continue
        img_bytes, img_ct = dl
        verdict = verify_image(
            image_bytes=img_bytes, content_type=img_ct,
            category=it.category, color=it.color_primary, name=it.name,
            budget=verify_budget, usage=usage,
        )
        if getattr(verdict, "skipped", False):
            report.verify_skipped += 1
            continue

        if _invariant_ok(verdict):
            it.invariant_checked_at = _now_utc()
            if it.person_status != "person_free":
                it.person_status = "person_free"  # the displayed image is person-free
            report.revalidated_pass += 1
            db.commit()
            continue

        report.revalidated_fail += 1
        it.generation_status = "pending_retry"  # masks the item for EVERY source
        if verdict.person_present:
            it.person_status = "person_present"
        db.commit()
        report.demoted += 1

        if gen_budget.remaining <= 0:
            report.budget_stopped = True
            continue
        g = generate_from_reference_bytes(
            reference_bytes=img_bytes, reference_content_type=img_ct,
            name=it.name, category=it.category, color=it.color_primary,
            brand=it.brand, pattern=None,
            storage_client=storage_client, user_id=it.user_id,
            gen_budget=gen_budget, verify_budget=verify_budget, usage=usage,
        )
        if g.outcome == "ready" and g.url:
            it.image_url = g.url
            it.generation_status = "ready"
            it.generation_attempts = 0
            it.person_status = "person_free"
            it.invariant_checked_at = _now_utc()
            db.commit()
            _maybe_promote_card(
                brand=it.brand, name=it.name, color=it.color_primary,
                url=g.url, content_sha256=g.content_sha256, verify_score=g.verify_score,
            )
            report.regenerated += 1
        elif g.outcome == "budget":
            report.budget_stopped = True
        else:
            _bump_attempts(it)
            if it.generation_status == "failed":
                report.terminal_failed += 1
            db.commit()


def _purge_legacy_crops(db: Session, report: SweepReport, storage_client) -> None:
    """B3: retroactive P5 purge — terminal photo/manual rows still holding crops."""
    for cand in _b3_query(db).all():
        _purge_crop_reference(cand, storage_client)
        report.crops_purged += 1
        db.commit()
