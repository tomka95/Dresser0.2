"""Phase 3d-a swipe-review service: list pending candidates + confirm (accept/reject).

The swipe deck reads the user's status='pending' candidates (GET
/gmail/ingest/candidates); the user's accept / reject / edit decisions POST to
/gmail/ingest/confirm, which is the ONLY path that writes the closet.

  * ACCEPTED candidates have their edits applied, then UPSERT into clothing_items on
    the existing UNIQUE(user_id, source_line_key) dedup key (migration 0006), so
    re-confirming the same candidate UPDATEs the existing row instead of inserting a
    duplicate. The candidate is marked status='accepted'.
  * REJECTED candidates are marked status='rejected' and write NOTHING to the closet.

SECURITY MODEL
--------------
user_id ALWAYS comes from the authenticated caller (the route passes
current_user.id); it is NEVER read from the request body. Every candidate_id in the
request is validated to belong to that user before any write — cross-user / unknown
ids are refused with ConfirmError. The application connects as the Postgres owner
role (RLS bypassed by the role, exactly as the fetch/extraction services do), so the
authoritative user scoping is the explicit `user_id == ...` filter HERE; the per-user
RLS policies on these tables are defense-in-depth for any direct/anon DB access, not
the primary guard.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func, literal_column
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.gmail_closet.extraction_schema import normalize_currency, normalize_order_date
from app.gmail_closet.product_image_cache import make_cache_key
from app.models import ClothingItem, GoogleAccount, IngestCandidate
from app.services.readiness import (
    TERMINAL_STATES,
    has_verified_card,
    mark_candidate_ready,
    needs_size,
    tags_ready,
)
from app.services.closet_canonicalize import (
    CanonFields,
    canonicalize_fields,
    load_user_facts,
)

logger = logging.getLogger(__name__)


# Fields the swipe UI can flag as weak (null value OR low per-field confidence).
_CONF_FIELDS = ("name", "brand", "category", "color", "size", "unit_price")
# At or above this per-field confidence the field is considered solid; below it (or
# a null score / null value) it is surfaced in low_confidence_fields for review.
_LOW_CONFIDENCE_THRESHOLD = 0.6

# Fields a confirm edit may set on a candidate before it is written to the closet.
_EDITABLE_FIELDS = frozenset(
    {"name", "brand", "category", "color", "size", "quantity",
     "unit_price", "currency", "order_date", "is_return"}
)
# Closet category enum (mirrors ClosetCategory / packages/contracts).
_CATEGORY_ENUM = frozenset(
    {"top", "bottom", "dress", "outerwear", "shoes", "accessories", "other"}
)


class ConfirmError(ValueError):
    """A confirm request was malformed, referenced a non-owned id, or had a bad edit.

    The route maps this to HTTP 400. The message is safe to surface (it names only
    ids and field names, never email content).
    """


# ---------------------------------------------------------------------------
# GET /gmail/ingest/candidates
# ---------------------------------------------------------------------------

def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _low_confidence_fields(c: IngestCandidate) -> List[str]:
    """Fields the UI should flag for edit: the value is null/blank OR its per-field
    confidence (from confidence_json["fields"]) is missing or below the threshold."""
    cj = c.confidence_json if isinstance(c.confidence_json, dict) else {}
    per_field = cj.get("fields") if isinstance(cj.get("fields"), dict) else {}

    weak: List[str] = []
    for f in _CONF_FIELDS:
        value = getattr(c, f, None)
        is_blank = value is None or (isinstance(value, str) and not value.strip())
        score = per_field.get(f)
        is_low = not isinstance(score, (int, float)) or score < _LOW_CONFIDENCE_THRESHOLD
        if is_blank or is_low:
            weak.append(f)
    return weak


def _failure_reason(c: IngestCandidate) -> str:
    """A short, honest, redaction-safe reason a candidate went terminal 'failed'.

    Never leaks image content — derived purely from the row's state. A person-in-frame
    failure (generation couldn't produce a person-free card after the attempt ceiling)
    is the common case for photo uploads."""
    if (c.person_status or "") == "person_present":
        return "We couldn't create a clean product image without the person in it."
    return "We couldn't create a clean product image for this one."


def _candidate_to_view(c: IngestCandidate, google_account_id: Optional[int]) -> Dict[str, Any]:
    """Serialize one candidate into the swipe-deck shape (JSON-ready dict).

    A 'failed' candidate is surfaced HONESTLY (Fix 2, 2026-07-10): review_state='failed'
    with a reason + name/category, and EVERY image field forced to None — the terminal
    failure is often a person-in-frame the generator couldn't remove, and the universal
    invariant forbids ever displaying that crop. The FE renders a 'couldn't process'
    entry (placeholder + reason + Retry/Dismiss), never a card."""
    is_failed = c.pipeline_state == "failed"
    if is_failed:
        return {
            "candidate_id": str(c.id),
            "name": c.name,
            "brand": c.brand,
            "category": c.category,
            "color": c.color,
            "size": c.size,
            "qty": c.quantity or 1,
            "unit_price": _to_float(c.unit_price),
            "currency": c.currency,
            "order_date": c.order_date.isoformat() if c.order_date else None,
            "is_return": bool(c.is_return),
            # INVARIANT: a failed candidate NEVER emits any image (may contain a person).
            "image_url": None,
            "generated_image_url": None,
            "on_model": bool(c.on_model),
            "person_status": c.person_status,
            "pipeline_state": c.pipeline_state,
            "image_status": c.image_status,
            "generation_status": c.generation_status,
            "needs_size": False,
            "review_state": "failed",
            "failure_reason": _failure_reason(c),
            "confidence_overall": _to_float(c.confidence_overall),
            "low_confidence_fields": _low_confidence_fields(c),
            "seen_count": c.seen_count or 1,
            "source_type": c.source_type or "gmail",
            "source": {
                "merchant": c.merchant, "order_id": c.order_id,
                "message_id": c.message_id, "google_account_id": google_account_id,
                "email_date": None,
            },
        }
    return {
        "review_state": "ready",
        "failure_reason": None,
        "candidate_id": str(c.id),
        "name": c.name,
        "brand": c.brand,
        "category": c.category,
        "color": c.color,
        "size": c.size,
        "qty": c.quantity or 1,
        "unit_price": _to_float(c.unit_price),
        "currency": c.currency,
        "order_date": c.order_date.isoformat() if c.order_date else None,
        "is_return": bool(c.is_return),
        # DISPLAY PURITY (Photo-seam Phase 5). On a photo/manual CANDIDATE image_url is
        # ALWAYS the raw source crop / uploaded reference — a GENERATION REFERENCE,
        # never a display source — so it is NEVER emitted for those sources (this also
        # closes the old leak where a person-containing crop URL rode along in the
        # payload after generation flipped person_status to person_free). The deck
        # shows generated_image_url once ready, a neutral panel until then. A gmail
        # candidate's image_url IS its verified resolved product image: sent only on
        # an AFFIRMATIVE person_free verdict; 'unknown'/'person_present' stay masked.
        "image_url": (
            c.image_url
            if (c.source_type or "gmail") == "gmail" and c.person_status == "person_free"
            else None
        ),
        "on_model": bool(c.on_model),
        "person_status": c.person_status,
        "pipeline_state": c.pipeline_state,
        # Phase 4 streaming deck: resolved | pending (still resolving — shimmer + poll) |
        # placeholder (slow tiers exhausted — static placeholder, stop polling) | null.
        "image_status": c.image_status,
        # Wave 2 generation card + lifecycle (photo only; null for Gmail). The deck
        # shows generated_image_url once generation_status='ready'; while 'generating'
        # it keeps polling. image_url stays the raw crop (verify reference + fallback).
        "generated_image_url": c.generated_image_url,
        "generation_status": c.generation_status,
        # Photo-seam Phase 3: the card is verified + person-free but held from 'ready'
        # ONLY by a missing size (no onboarding default). The deck shows an "add size"
        # affordance; supplying a size at confirm completes it.
        "needs_size": needs_size(c),
        "confidence_overall": _to_float(c.confidence_overall),
        "low_confidence_fields": _low_confidence_fields(c),
        "seen_count": c.seen_count or 1,
        # Ingestion source ('gmail' | 'photo') so the deck shows a source-aware badge.
        "source_type": c.source_type or "gmail",
        "source": {
            "merchant": c.merchant,
            "order_id": c.order_id,
            "message_id": c.message_id,
            "google_account_id": google_account_id,
            # null for now: the email's received date isn't persisted on the candidate
            # this phase (same "null for now" treatment as image_url). Re-running the
            # extraction pass once a date column is added will populate it.
            "email_date": None,
        },
    }


def list_pending_candidates(
    db: Session, user_id: UUID, sync_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Return the user's status='pending' candidates for the swipe deck.

    Phase 4 ordering: image-PRESENT candidates first, then the still-resolving
    (imageless) ones — so the user swipes ready cards while the background fill streams
    images onto the rest. Within each group, ranked most-confident first
    (confidence_overall DESC, nulls last), then newest. User-scoped by an explicit
    user_id filter (the owner-role connection bypasses RLS — see module docstring).

    ``sync_id`` scopes the deck to a SINGLE run. The photo flow passes the run created
    by /photo/ingest/commit so its deck shows only that upload's garments — never stale
    pending candidates from an earlier (Gmail or photo) run. When None (the Gmail deck),
    behavior is unchanged: all of the user's pending candidates. status='pending' is
    always enforced, so already accepted/rejected candidates never reappear either way.
    """
    # One Gmail account per user (UNIQUE(user_id)); use its id as the source account.
    account = (
        db.query(GoogleAccount.id)
        .filter(GoogleAccount.user_id == user_id)
        .first()
    )
    ga_id = account[0] if account else None

    q = db.query(IngestCandidate).filter(
        IngestCandidate.user_id == user_id,
        IngestCandidate.status == "pending",
        # The deck serves: 'ready' (verified person-free card, tag-complete), any
        # 'verified_clean' row that HOLDS a verified card (size is now OPTIONAL, so
        # these are ready-eligible normal cards — Fix 1), AND 'failed' rows so a user
        # who selected a zone always SEES it accounted for (Fix 2, no silent drops).
        IngestCandidate.pipeline_state.in_(("ready", "verified_clean", "failed")),
    )
    if sync_id is not None:
        q = q.filter(IngestCandidate.sync_id == sync_id)

    rows = (
        q
        .order_by(
            # image present (image_url NOT NULL) sorts before imageless: `IS NULL`
            # yields false(0) for present rows, true(1) for imageless — ascending puts
            # the ready cards first.
            IngestCandidate.image_url.is_(None).asc(),
            IngestCandidate.confidence_overall.desc().nullslast(),
            IngestCandidate.created_at.desc(),
        )
        .all()
    )
    # 'ready' + 'failed' pass verbatim; 'verified_clean' passes ONLY when it holds a
    # verified card (a card-less verified_clean is still in flight, not reviewable).
    rows = [
        c for c in rows
        if c.pipeline_state in ("ready", "failed") or has_verified_card(c)
    ]
    failed_count = sum(1 for c in rows if c.pipeline_state == "failed")
    if failed_count:
        logger.info(
            "deck user=%s sync=%s: %d failed candidate(s) surfaced for review",
            user_id, sync_id or "*", failed_count,
        )
    return [_candidate_to_view(c, ga_id) for c in rows]


# ---------------------------------------------------------------------------
# THE whole-batch settle (Photo-seam Phase 3) — shared by the Home banner and
# the photo status poll. ONE authoritative condition, per batch (sync_id).
# ---------------------------------------------------------------------------

@dataclass
class SettleCounts:
    """Per-batch readiness accounting (ids+counts only, redaction-safe).

    settled ⟺ zero pending candidates are still mid-pipeline. A batch member counts as
    settled when it is TERMINAL: 'ready' (verified invariant-compliant card) or 'failed'
    (surfaced in the deck as a 'couldn't process' entry with Retry/Dismiss — Fix 2, no
    longer silently excluded). reviewable = everything the deck serves for the user to
    act on: ready cards + failed entries (both are shown; failed needs Retry/Dismiss)."""
    ready: int = 0
    failed: int = 0
    needs_size: int = 0
    unsettled: int = 0

    @property
    def settled(self) -> bool:
        return self.unsettled == 0

    @property
    def reviewable(self) -> int:
        # Fix 2: failed items ARE reviewable (the user must see + Retry/Dismiss them),
        # so an all-failed batch still surfaces rather than vanishing.
        return self.ready + self.failed


def settle_counts(db: Session, user_id: UUID, sync_id: str) -> SettleCounts:
    """Classify a batch's pending candidates into the settle buckets.

    Loaded + classified in python via the SAME readiness predicates the deck and the
    ready-writer use (needs_size / terminal states) — one truth, no SQL/py drift.
    Batches are small (photo: zones of one upload; gmail: one scan's staging)."""
    rows = (
        db.query(IngestCandidate)
        .filter(
            IngestCandidate.user_id == user_id,
            IngestCandidate.sync_id == str(sync_id),
            IngestCandidate.status == "pending",
        )
        .all()
    )
    out = SettleCounts()
    for c in rows:
        # Demoted recommendation/ad rows (0040) are OUT of batch accounting entirely:
        # they are terminal audit rows, never reviewable, and must not block settle.
        if c.pipeline_state == "rejected_recommendation":
            continue
        # needs_enrichment rows are admitted purchases EXCLUDED from generation until
        # they get a real product name — mid-pipeline by design, not "in flight", so
        # they must not hold the whole batch's banner hostage either.
        if c.needs_enrichment and c.pipeline_state not in ("ready", "failed"):
            continue
        # ready, or verified_clean holding a verified card (ready-eligible now that size
        # is optional — the deck serves it as a normal card) both count as reviewable.
        if c.pipeline_state == "ready" or (
            c.pipeline_state == "verified_clean" and has_verified_card(c)
        ):
            out.ready += 1
            if needs_size(c):
                out.needs_size += 1   # soft: a card that could still take a size
        elif c.pipeline_state == "failed":
            out.failed += 1
        else:
            out.unsettled += 1
    return out


def retry_candidate(db: Session, user_id: UUID, candidate_id: str) -> bool:
    """Re-queue a terminal-'failed' candidate through the shared generation seam (Fix 2).

    Resets the attempt ledger + returns it to heal-eligible 'pending_retry' /
    'image_pending' so the self-heal sweep re-runs it through flux2->nano->verify. Only
    a 'failed' row the caller owns is eligible; anything else is a no-op False. The
    caller dispatches the background self-heal. Never raises image content into logs."""
    try:
        cid = UUID(str(candidate_id))
    except (ValueError, TypeError):
        return False
    cand = (
        db.query(IngestCandidate)
        .filter(IngestCandidate.id == cid, IngestCandidate.user_id == user_id)
        .first()
    )
    if cand is None or cand.pipeline_state != "failed":
        return False
    cand.generation_attempts = 0
    cand.generation_status = "pending_retry"
    cand.pipeline_state = "image_pending"
    db.commit()
    logger.info("candidate retry user=%s cand=%s -> pending_retry", user_id, cid)
    return True


def dismiss_candidate(db: Session, user_id: UUID, candidate_id: str) -> bool:
    """Dismiss a candidate from review (Fix 2). Marks status='rejected' so it leaves the
    pending deck for good — same terminal outcome as a swipe-reject, nothing written to
    the closet. Owner-scoped; a foreign/unknown id is a no-op False."""
    try:
        cid = UUID(str(candidate_id))
    except (ValueError, TypeError):
        return False
    cand = (
        db.query(IngestCandidate)
        .filter(IngestCandidate.id == cid, IngestCandidate.user_id == user_id)
        .first()
    )
    if cand is None:
        return False
    cand.status = "rejected"
    db.commit()
    logger.info("candidate dismissed user=%s cand=%s", user_id, cid)
    return True


# ---------------------------------------------------------------------------
# POST /gmail/ingest/confirm
# ---------------------------------------------------------------------------

@dataclass
class WrittenItem:
    """One clothing_items row written by an accept (insert or dedup-update)."""
    clothing_item_id: str
    candidate_id: str
    name: str
    source_line_key: Optional[str]
    inserted: bool   # True = new row; False = ON CONFLICT update (dedup hit)


@dataclass
class ConfirmResult:
    accepted_count: int = 0          # candidates marked accepted
    rejected_count: int = 0          # candidates marked rejected
    inserted_count: int = 0          # NEW clothing_items rows
    updated_count: int = 0           # existing rows updated (dedup hits)
    written: List[WrittenItem] = field(default_factory=list)


def _parse_ids(raw: Optional[List[str]], label: str) -> List[UUID]:
    out: List[UUID] = []
    for r in raw or []:
        try:
            out.append(UUID(str(r)))
        except (ValueError, TypeError):
            raise ConfirmError(f"{label}: '{r}' is not a valid candidate id")
    return out


def _apply_edits(cand: IngestCandidate, edits: Dict[str, Any]) -> None:
    """Validate + apply a candidate's edits in place (raises ConfirmError on bad input).

    The edited values are persisted onto the candidate row AND used to build the
    clothing_items write, so a later re-confirm reproduces the same closet row. The
    content-based source_line_key is deliberately NOT recomputed — it is the stable
    dedup key and must not move when the user corrects a display field.
    """
    for fname, value in (edits or {}).items():
        if fname not in _EDITABLE_FIELDS:
            raise ConfirmError(f"candidate {cand.id}: '{fname}' is not an editable field")

        if fname == "name":
            if value is None or not str(value).strip():
                raise ConfirmError(f"candidate {cand.id}: name cannot be empty")
            cand.name = str(value).strip()
        elif fname == "quantity":
            try:
                q = int(value)
            except (TypeError, ValueError):
                raise ConfirmError(f"candidate {cand.id}: quantity must be an integer")
            if q < 1:
                raise ConfirmError(f"candidate {cand.id}: quantity must be >= 1")
            cand.quantity = q
        elif fname == "unit_price":
            if value is None:
                cand.unit_price = None
            else:
                try:
                    cand.unit_price = float(value)
                except (TypeError, ValueError):
                    raise ConfirmError(f"candidate {cand.id}: unit_price must be numeric")
        elif fname == "currency":
            cand.currency = normalize_currency(str(value)) if value else None
        elif fname == "order_date":
            cand.order_date = normalize_order_date(str(value)) if value else None
        elif fname == "is_return":
            cand.is_return = bool(value)
        elif fname == "category":
            if value is not None and value not in _CATEGORY_ENUM:
                raise ConfirmError(
                    f"candidate {cand.id}: category must be one of {sorted(_CATEGORY_ENUM)}"
                )
            cand.category = value
        else:  # brand, color, size — free text or null
            setattr(cand, fname, str(value).strip() if value is not None else None)


def _used_generated_card(cand: IngestCandidate) -> bool:
    """True iff this candidate has a VERIFIED generated card to store (ready + a card URL)."""
    return cand.generation_status == "ready" and bool(cand.generated_image_url)


def _item_generation_status(cand: IngestCandidate) -> Optional[str]:
    """The generation_status to write onto the clothing_item (G6).

    An ON-MODEL item is 'ready' — which the closet read UNMASKS — ONLY when it carries the
    verified generated card. If confirm falls back to the raw crop (a 'ready' candidate with
    no generated_image_url, or any non-ready state), force 'pending_retry' for on-model so
    the read keeps it MASKED: a crop that may contain a person can never be unmasked. Non-
    on-model items keep the candidate's status verbatim (unchanged behavior)."""
    if cand.on_model and not _used_generated_card(cand):
        return "pending_retry"
    return cand.generation_status


def _upsert_clothing_item(
    db: Session,
    user_id: UUID,
    cand: IngestCandidate,
    ga_id: Optional[int],
    user_facts: Optional[Dict[str, Any]] = None,
) -> WrittenItem:
    """UPSERT one accepted candidate into clothing_items on UNIQUE(user_id, source_line_key).

    ON CONFLICT DO UPDATE refreshes the carried fields (so applied edits land even on
    a re-confirm) and bumps updated_at; it never inserts a duplicate. The RETURNING
    `(xmax = 0)` flag distinguishes a fresh INSERT (true) from a dedup UPDATE (false).

    Every core field passes through the ONE canonicalization chokepoint
    (app.services.closet_canonicalize) FIRST: category is guaranteed non-null, name is
    guaranteed descriptive, size defaults from the user's onboarding sizes (facts.sizes,
    passed as ``user_facts``), and the provenance='extracted' attributes_json seed is
    built there. Common items resolve with zero LLM calls (pure rules + a size lookup).
    """
    tbl = ClothingItem.__table__
    # Wave 2a: persist merchant onto the closet row (no more display-time join) and
    # seed the image lifecycle fields. image_status carries the candidate's lifecycle
    # forward: 'resolved' when it has an image, terminal 'placeholder' when the
    # background fill already exhausted the slow tiers, else 'pending' (the self-heal
    # pass re-resolves these cache-first later). image_cache_key links the row to the
    # shared product-image cache.
    if cand.image_status == "user_uploaded":
        # Photo-sourced cutout: its own terminal lifecycle state (not the resolve/
        # verify pipeline). Preserve it rather than relabeling as 'resolved'.
        image_status = "user_uploaded"
    elif cand.image_url:
        image_status = "resolved"
    elif cand.image_status == "placeholder":
        image_status = "placeholder"
    else:
        image_status = "pending"
    image_cache_key = make_cache_key(cand.brand, cand.name, cand.color)
    # Wave 2 confirm-attach: the closet row must show the VERIFIED generated product
    # card, NOT the raw crop. Only 'ready' (with a stored card) uses generated_image_url;
    # every other generation_status — pending_retry / failed / null, i.e. no verified
    # card — falls back to the crop (image_url) so the item still has an image. The
    # candidate's generation_status is carried forward so a later generation self-heal
    # can find the 'pending_retry' closet rows and re-attempt (image_url is the crop it
    # regenerates from).
    if _used_generated_card(cand):
        closet_image_url = cand.generated_image_url
    else:
        closet_image_url = cand.image_url
    # G6: an on-model item is 'ready' (which the closet read UNMASKS) ONLY when it carries
    # the VERIFIED generated card — see _item_generation_status.
    item_generation_status = _item_generation_status(cand)
    # THE canonicalization chokepoint. Folds legacy category aliases + guarantees a
    # non-null category, a descriptive name, and a profile-defaulted size, and builds the
    # provenance seed (source values -> 'extracted'; derived -> 'inferred'; size default /
    # 'other' -> 'default'). Seeded on INSERT only (NOT in the on_conflict set_ below), so
    # a re-confirm never clobbers a row the enricher/user has since enriched/edited.
    cj = cand.confidence_json if isinstance(cand.confidence_json, dict) else {}
    per_field = cj.get("fields") if isinstance(cj.get("fields"), dict) else None
    canon = canonicalize_fields(
        CanonFields(
            name=cand.name,
            category=cand.category,
            color=cand.color,
            brand=cand.brand,
            size=cand.size,
            merchant=cand.merchant,
            confidence=per_field if isinstance(per_field, dict) else None,
        ),
        user_facts,
        source_provenance="extracted",
    )
    category = canon.category
    extracted_attrs = canon.attributes
    vals = dict(
        user_id=user_id,
        name=canon.name,
        category=category,
        color_primary=canon.color,
        brand=canon.brand,
        size=canon.size,
        quantity=cand.quantity or 1,
        unit_price=cand.unit_price,
        currency=cand.currency,
        order_date=cand.order_date,
        is_return=bool(cand.is_return),
        order_id=cand.order_id,
        source_message_id=cand.message_id,
        source_google_account_id=ga_id,
        source_line_key=cand.source_line_key,
        ingest_confidence=cand.confidence_overall,
        image_url=closet_image_url,
        merchant=cand.merchant,
        image_status=image_status,
        image_cache_key=image_cache_key,
        generation_status=item_generation_status,
        # Carry the ingestion source forward ('gmail' | 'photo') so the closet records
        # how each item arrived. The candidate's value is server-set at stage time.
        source_type=cand.source_type,
        # G6: carry the on-model flag. image_url above holds the crop ONLY as the gen/self-
        # heal reference; the closet read masks it until a verified person-free card lands.
        on_model=bool(cand.on_model),
        # Ready-first Phase 1: carry the fail-closed person tri-state. When confirm stores
        # the VERIFIED generated card, the stored image is person-free by construction —
        # regardless of what the source was. Otherwise the candidate's verdict (or lack of
        # one: 'unknown' stays masked) travels with the item.
        person_status=(
            "person_free" if _used_generated_card(cand) else (cand.person_status or "unknown")
        ),
        # Photo-seam Phase 6: the candidate's verify-v2 validation marker travels with
        # the item (a card born v2-compliant needs no backfill re-check).
        invariant_checked_at=cand.invariant_checked_at,
        # Generation observability (0039): carry which provider produced the card + cost.
        generation_provider=getattr(cand, "generation_provider", None),
        generation_cost_usd=getattr(cand, "generation_cost_usd", None),
        # provenance='extracted' seed. INSERT-only: NOT in the on_conflict set_ below, so
        # a re-confirm preserves any 'inferred'/'user_edited' attributes already present.
        attributes_json=extracted_attrs,
    )
    stmt = pg_insert(tbl).values(**vals)
    ex = stmt.excluded
    stmt = stmt.on_conflict_do_update(
        constraint="clothing_items_user_id_source_line_key_key",
        set_={
            "name": ex.name,
            "category": ex.category,
            "color_primary": ex.color_primary,
            "brand": ex.brand,
            "size": ex.size,
            "quantity": ex.quantity,
            "unit_price": ex.unit_price,
            "currency": ex.currency,
            "order_date": ex.order_date,
            "is_return": ex.is_return,
            "order_id": ex.order_id,
            "source_message_id": ex.source_message_id,
            "source_google_account_id": ex.source_google_account_id,
            "ingest_confidence": ex.ingest_confidence,
            "image_url": ex.image_url,
            "merchant": ex.merchant,
            "image_status": ex.image_status,
            "image_cache_key": ex.image_cache_key,
            "generation_status": ex.generation_status,
            "source_type": ex.source_type,
            "on_model": ex.on_model,
            "person_status": ex.person_status,
            "invariant_checked_at": ex.invariant_checked_at,
            "generation_provider": ex.generation_provider,
            "generation_cost_usd": ex.generation_cost_usd,
            "updated_at": func.now(),
        },
    ).returning(tbl.c.id, literal_column("(xmax = 0)").label("inserted"))

    row = db.execute(stmt).one()
    return WrittenItem(
        clothing_item_id=str(row.id),
        candidate_id=str(cand.id),
        name=cand.name,
        source_line_key=cand.source_line_key,
        inserted=bool(row.inserted),
    )


def confirm_candidates(
    db: Session,
    user_id: UUID,
    accepted: Optional[List[str]] = None,
    rejected: Optional[List[str]] = None,
    edits: Optional[Dict[str, Dict[str, Any]]] = None,
) -> ConfirmResult:
    """Apply a swipe-review decision. user_id is the authenticated caller (never the body).

    accepted/rejected are candidate-id lists; edits maps candidate_id -> {field: value}
    and every edited id MUST also be in accepted. All ids are validated to belong to
    the caller before any write; the whole operation commits atomically.
    """
    accepted_ids = _parse_ids(accepted, "accepted")
    rejected_ids = _parse_ids(rejected, "rejected")
    edits = edits or {}

    accepted_set = set(accepted_ids)
    rejected_set = set(rejected_ids)

    overlap = accepted_set & rejected_set
    if overlap:
        raise ConfirmError(
            f"candidate(s) in both accepted and rejected: {[str(i) for i in overlap]}"
        )

    # Edits only make sense for accepted candidates.
    edit_ids = _parse_ids(list(edits.keys()), "edits")
    stray_edits = set(edit_ids) - accepted_set
    if stray_edits:
        raise ConfirmError(
            f"edits reference candidate(s) not in accepted: {[str(i) for i in stray_edits]}"
        )

    referenced = accepted_set | rejected_set | set(edit_ids)
    if not referenced:
        return ConfirmResult()

    # Load ONLY the caller's candidates among those referenced. Anything missing was
    # either unknown or owned by another user — both are refused.
    owned = (
        db.query(IngestCandidate)
        .filter(
            IngestCandidate.user_id == user_id,
            IngestCandidate.id.in_(referenced),
        )
        .all()
    )
    by_id = {c.id: c for c in owned}
    missing = referenced - set(by_id.keys())
    if missing:
        raise ConfirmError(
            f"unknown or non-owned candidate id(s): {[str(i) for i in missing]}"
        )

    # Map edits onto UUID keys for lookup.
    edits_by_uuid = {UUID(str(k)): v for k, v in edits.items()}

    # One Gmail account per user; carried as clothing_items.source_google_account_id.
    account = (
        db.query(GoogleAccount.id)
        .filter(GoogleAccount.user_id == user_id)
        .first()
    )
    ga_id = account[0] if account else None

    # The user's onboarding sizes (facts.sizes) — loaded ONCE, passed to every upsert so
    # canonicalize can default an empty size by category. {} when the user has no profile.
    user_facts = load_user_facts(db, user_id)

    result = ConfirmResult()

    # --- Accepts: apply edits -> validate -> upsert -> mark accepted ----------
    for cid in accepted_ids:
        cand = by_id[cid]
        if cid in edits_by_uuid:
            _apply_edits(cand, edits_by_uuid[cid])
        if not cand.name or not str(cand.name).strip():
            # clothing_items.name is NOT NULL; refuse rather than write a blank item.
            raise ConfirmError(f"candidate {cid}: name is required to accept")

        # A verified_clean card (verified person-free image + name + category) is now
        # ready-eligible — size is OPTIONAL (Fix 1), so tags_ready no longer needs it.
        # Complete the state machine through THE shared ready writer. (A user-supplied
        # size edit still attaches; it just isn't required.)
        if (
            cand.pipeline_state not in TERMINAL_STATES
            and cand.person_status == "person_free"
            and has_verified_card(cand)
            and tags_ready(cand)
        ):
            mark_candidate_ready(cand)

        # THE CONFIRM CHOKEPOINT (Photo-seam Phase 4): a closet item may ONLY be born
        # from a 'ready' candidate — verified, person-free, invariant-compliant image +
        # complete tags (name + category; size optional), asserted by the single
        # ready-writer above. Every entry point (photo deck, gmail deck, manual add,
        # chat add) funnels through here; there is no other clothing_items insert path
        # (tests enumerate this). A 'failed' candidate is never accepted — it is
        # Retried or Dismissed instead (Fix 2), never silently written.
        if cand.pipeline_state != "ready":
            raise ConfirmError(
                f"candidate {cid}: not ready for the closet (state={cand.pipeline_state})"
            )

        written = _upsert_clothing_item(db, user_id, cand, ga_id, user_facts)
        result.written.append(written)
        if written.inserted:
            result.inserted_count += 1
        else:
            result.updated_count += 1
        cand.status = "accepted"
        result.accepted_count += 1

    # --- Rejects: mark only, write nothing to the closet ----------------------
    for cid in rejected_ids:
        by_id[cid].status = "rejected"
        result.rejected_count += 1

    db.commit()

    logger.info(
        "confirm user=%s: accepted=%d (inserted=%d updated=%d) rejected=%d",
        user_id, result.accepted_count, result.inserted_count,
        result.updated_count, result.rejected_count,
    )
    return result
