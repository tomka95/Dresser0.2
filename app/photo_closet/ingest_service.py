"""Photo -> closet ingest orchestrator (Wave 1.5: detect / select / commit).

Wave 1 ran the whole pipeline in one request. Wave 1.5 splits it around the user's
region selection:

  run_photo_detect  — validate-already-done images -> duplicate check (read-only) ->
                      Gemini detect -> persist the regions in a transient
                      photo_detect_sessions row. NO cutouts, NO storage writes, NO
                      processed_uploads, NO ingest_runs. The source photo is never
                      persisted (unchanged invariant) — the session holds hashes,
                      dimensions, boxes, and model masks only.

  run_photo_commit  — the client re-uploads the SAME files plus its selection; each
                      file is re-bound to its session by sha256. Only the SELECTED
                      detected regions (plus any user-drawn manual boxes) are cut
                      out, stored, and staged as ingest_candidates. This is where
                      ingest_runs + processed_uploads are written.

The candidates then flow through the SAME GET /…/candidates deck and POST
/…/confirm path as Gmail — this module never writes clothing_items itself.

Everything here is user-scoped by an explicit ``user_id`` (server-pinned from the JWT
by the route); nothing reads identity from the request. The staging upsert is written
dialect-agnostically (select-then-insert/update on the UNIQUE(user_id, source_line_key)
key) so it behaves identically on Postgres and the SQLite test DB.
"""
from __future__ import annotations

import hashlib
import io
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from PIL import Image
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import IngestCandidate, IngestRun, PhotoDetectSession, ProcessedUpload
from app.photo_closet.cutout import build_cutout
from app.photo_closet.dedup import dedup_check
from app.services.closet_canonicalize import default_size_for_category, load_user_facts
from app.services.readiness import TERMINAL_STATES, advance, mark_candidate_ready, tags_ready
from app.photo_closet.detection import (
    DetectionResult,
    GarmentCategory,
    GarmentDescription,
    GarmentRegion,
    describe_garment_crop,
    detect_garments_with_regions,
)
from app.utils.image_validation import SanitizedImage, phash_distance

logger = logging.getLogger(__name__)

# Near-duplicate threshold (Hamming distance over the 64-bit dHash). <= this and we
# treat a freshly-uploaded photo as a re-upload and skip the full detect+stage pass.
NEAR_DUP_DISTANCE = 6
# How many of a user's recent processed-upload phashes to scan for near-dups.
_NEAR_DUP_SCAN_LIMIT = 500
# Cap on user-drawn boxes per photo at commit (each is a Gemini describe call).
MAX_MANUAL_BOXES_PER_PHOTO = 8
# Max chars kept from a user-supplied manual-box name (trimmed; longer is truncated).
MAX_MANUAL_NAME_LEN = 120


# --- Commit error taxonomy (the route maps these to HTTP codes) ---------------

class PhotoCommitError(Exception):
    """Base class for commit-selection failures. Messages are user-safe."""


class PhotoSessionNotFound(PhotoCommitError):
    """Unknown session id, or a session owned by another user (indistinguishable)."""


class PhotoSessionExpired(PhotoCommitError):
    """The session's TTL has passed; the client must re-run detect."""


class PhotoSessionConflict(PhotoCommitError):
    """Session already committed, or the matching file was not re-uploaded."""


class PhotoSelectionInvalid(PhotoCommitError):
    """Malformed selection payload: bad region ids or manual boxes."""


# --- Result / input shapes ----------------------------------------------------

@dataclass
class PhotoDetectOutcome:
    """Per-photo result of run_photo_detect, in upload order. ``regions`` carries
    NO masks (they stay in the session row, server-side only)."""

    session_id: Optional[str]   # None when the photo was a duplicate (no session)
    image_sha256: str
    width: int
    height: int
    duplicate: bool
    person_count: int
    regions: List[dict] = field(default_factory=list)


@dataclass(frozen=True)
class PhotoSelection:
    """One photo's commit instruction (parsed from the route's selections JSON)."""

    session_id: str
    selected_region_ids: List[int] = field(default_factory=list)
    # Heterogeneous by design (contract v2): each entry is EITHER a legacy geometry-only
    # box [ymin,xmin,ymax,xmax] OR an object {"box": [...], "name"?: str}. _parse_manual_box
    # normalizes both; a supplied name replaces the auto-describe for that candidate.
    manual_boxes: List = field(default_factory=list)


@dataclass
class PhotoCommitResult:
    """Per-zone accounting (Photo-seam Phase 3, G2): every selected zone is accounted
    for — selected == staged + failed + zones inside duplicate photos. Nothing is ever
    silently dropped: a zone that cannot proceed is staged as a TERMINAL 'failed'
    candidate (visible in settle accounting), and a duplicate photo's zones are
    reported via `duplicates` (explicit dedup, per photo)."""
    sync_id: str
    images_processed: int = 0   # photos whose selection was staged (dups excluded)
    selected: int = 0           # zones requested (detected regions + manual boxes)
    staged: int = 0             # viable candidates staged across all photos
    failed: int = 0             # zones staged as terminal 'failed' (cutout/generation unavailable)
    duplicates: int = 0         # photos skipped: already committed elsewhere


# --- Shared helpers (unchanged from Wave 1) ------------------------------------

def store_cutout(storage_client, user_id: UUID, cut) -> Optional[str]:
    """Upload one cutout via the content-addressed image_blobs dedup; return its URL.

    Module-level so tests can monkeypatch it without a real bucket. Mirrors
    image_resolver._upload: identical bytes (any run, any user) reuse one stored URL.

    BEST-EFFORT: an upload failure (bucket down, bad credentials) returns None instead
    of raising — the same degraded outcome as storage_client=None, so a mid-batch
    storage outage stages the garment image-less rather than 500-ing the whole commit
    (matching the route's documented stage-without-images fallback).
    """
    if storage_client is None:
        return None
    from app.utils.image_blob_store import get_or_upload

    try:
        return get_or_upload(
            cut.data,
            lambda: storage_client.upload_bytes(
                cut.data,
                folder=f"photo_items/{user_id}",
                content_type=cut.content_type,
                suffix=cut.suffix,
            ),
        )
    except Exception as exc:
        logger.warning("store_cutout: upload failed (%s)", type(exc).__name__)
        return None


def _source_line_key(image_sha256: str, box_2d: List[int]) -> str:
    """Stable per-garment-region fingerprint: hash(image bytes id + box).

    Re-confirming the same staged candidate maps to the same clothing_items row via
    UNIQUE(user_id, source_line_key), so a photo garment never duplicates the closet.
    32 hex chars, mirroring the Gmail content-key width.
    """
    box = ",".join(str(int(v)) for v in (box_2d or []))
    digest = hashlib.sha256(f"photo:{image_sha256}:{box}".encode()).hexdigest()
    return digest[:32]


def _is_duplicate_upload(db: Session, user_id: UUID, sanitized: SanitizedImage) -> bool:
    """True if this exact file (sha256) or a near-dup (phash) was already processed."""
    exact = (
        db.query(ProcessedUpload.id)
        .filter(
            ProcessedUpload.user_id == user_id,
            ProcessedUpload.image_sha256 == sanitized.sha256,
        )
        .first()
    )
    if exact is not None:
        return True

    recent = (
        db.query(ProcessedUpload.phash)
        .filter(
            ProcessedUpload.user_id == user_id,
            ProcessedUpload.phash.isnot(None),
            ProcessedUpload.status == "processed",
        )
        .order_by(ProcessedUpload.processed_at.desc())
        .limit(_NEAR_DUP_SCAN_LIMIT)
        .all()
    )
    for (ph,) in recent:
        try:
            if phash_distance(sanitized.phash, ph) <= NEAR_DUP_DISTANCE:
                return True
        except (ValueError, TypeError):
            continue
    return False


def _stage_candidate(
    db: Session, user_id: UUID, sync_id: UUID, garment, image_url: Optional[str],
    source_line_key: str, *, on_model: bool = False, facts: Optional[dict] = None,
) -> IngestCandidate:
    """Upsert one garment as a pending photo candidate on UNIQUE(user_id, source_line_key).

    ``garment`` is any GarmentRegion-shaped object (GarmentRegion or
    GarmentDescription). Dialect-agnostic (select-then-insert/update) so it runs on
    SQLite + Postgres alike.

    ``on_model`` (G6): the source photo had a person (person_count>=1), so this cutout
    contains a person. It's kept only as the generation reference; the display layer masks
    it until a verified person-free card lands.

    ``facts`` (Photo-seam Phase 1, stage-time canonicalize-lite): the user's onboarding
    facts — a photo can't reveal a size, so the size defaults from facts.sizes exactly
    like the Gmail fill pass does. The shared readiness invariant requires size
    present-or-sizeless before a candidate may go 'ready'.
    """
    conf = garment.confidence
    confidence_json = {
        "fields": {
            "name": conf.name,
            "brand": conf.brand,
            "category": conf.category,
            "color": conf.color,
        }
    }
    category = garment.category.value
    fields = dict(
        sync_id=sync_id,
        message_id=None,
        source_message_ids=[],
        seen_count=1,
        name=garment.name,
        brand=garment.brand,
        category=category,
        color=garment.color,
        # Stage-time canonicalize-lite (same lookup the Gmail fill + confirm use).
        size=default_size_for_category((facts or {}).get("sizes"), category),
        image_url=image_url,
        image_status="user_uploaded",
        source_type="photo",
        on_model=on_model,
        # Ready-first Phase 1: readiness-machine entry state + fail-closed person signal.
        # The photo detector MEASURED person_count both ways, so this is an AFFIRMATIVE
        # verdict (unlike Gmail staging, which stays 'unknown' until a verify runs).
        pipeline_state="staged",
        person_status="person_present" if on_model else "person_free",
        confidence_overall=garment.confidence_overall,
        confidence_json=confidence_json,
        status="pending",
    )

    existing = (
        db.query(IngestCandidate)
        .filter(
            IngestCandidate.user_id == user_id,
            IngestCandidate.source_line_key == source_line_key,
        )
        .first()
    )
    if existing is not None:
        was_ready = existing.pipeline_state == "ready"
        for k, v in fields.items():
            setattr(existing, k, v)
        # A re-staged candidate that already carries a VERIFIED generated card stays
        # visible — resetting it to 'staged' would hide it from the ready-gated deck
        # forever (generation never re-selects generation_status='ready' rows). Restored
        # through the SHARED readiness machine: the retained card is verified person-free
        # by construction (so person_status goes affirmative WITH it — previously this
        # re-set 'ready' while the fields overwrite left person_status='person_present',
        # resurrecting a ready+person_present row, the exact inconsistency the shared
        # invariant forbids), and 'ready' via mark_candidate_ready. A row that was
        # ALREADY terminal-ready keeps 'ready' even if its tags are legacy-incomplete —
        # terminal states never regress on a re-upload of the same photo.
        if existing.generation_status == "ready" and existing.generated_image_url:
            existing.person_status = "person_free"
            advance(existing, "verified_clean")
            if tags_ready(existing):
                mark_candidate_ready(existing)
            elif was_ready:
                existing.pipeline_state = "ready"  # terminal immutability
        return existing

    cand = IngestCandidate(
        user_id=user_id, source_line_key=source_line_key, **fields
    )
    db.add(cand)
    return cand


# --- Wave 1.5 internals ---------------------------------------------------------

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    """Normalize a DB datetime for comparison (SQLite returns naive; Postgres aware)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _region_json(region_id: int, garment: GarmentRegion) -> dict:
    """One session-row region entry. The mask stays HERE (JSONB) and only here."""
    conf = garment.confidence
    return {
        "region_id": region_id,
        "box_2d": [int(v) for v in (garment.box_2d or [])],
        "mask": garment.mask,
        "name": garment.name,
        "category": garment.category.value,
        "color": garment.color,
        "pattern": garment.pattern,
        "material": garment.material,
        "fit": garment.fit,
        "brand": garment.brand,
        "confidence_overall": (
            float(garment.confidence_overall)
            if garment.confidence_overall is not None else None
        ),
        "confidence": {
            "name": conf.name,
            "category": conf.category,
            "color": conf.color,
            "pattern": conf.pattern,
            "material": conf.material,
            "fit": conf.fit,
            "brand": conf.brand,
        },
    }


def _region_public(region: dict) -> dict:
    """A region as returned to the client: everything EXCEPT the mask."""
    return {k: v for k, v in region.items() if k != "mask"}


def _validate_manual_box(box) -> List[int]:
    """[ymin, xmin, ymax, xmax], ints 0..1000, ymin<ymax and xmin<xmax — or raise."""
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        raise PhotoSelectionInvalid(
            "each manual box must be [ymin, xmin, ymax, xmax]")
    vals: List[int] = []
    for v in box:
        if isinstance(v, bool) or not isinstance(v, int):
            raise PhotoSelectionInvalid("manual box coordinates must be integers")
        if v < 0 or v > 1000:
            raise PhotoSelectionInvalid("manual box coordinates must be 0..1000")
        vals.append(v)
    ymin, xmin, ymax, xmax = vals
    if ymin >= ymax or xmin >= xmax:
        raise PhotoSelectionInvalid(
            "manual box must satisfy ymin < ymax and xmin < xmax")
    return vals


def _parse_manual_box(raw) -> Tuple[List[int], Optional[str]]:
    """Normalize a manual-box entry to (validated_box, optional_name).

    Accepts BOTH shapes (contract v2, backward compatible):
      * legacy geometry-only:  [ymin, xmin, ymax, xmax]
      * named:                 {"box": [ymin, xmin, ymax, xmax], "name"?: str}
    A blank/whitespace name normalizes to None (falls back to auto-describe)."""
    name: Optional[str] = None
    if isinstance(raw, dict):
        box = raw.get("box")
        raw_name = raw.get("name")
        if raw_name is not None:
            if not isinstance(raw_name, str):
                raise PhotoSelectionInvalid("manual box name must be a string")
            name = raw_name.strip()[:MAX_MANUAL_NAME_LEN] or None
    else:
        box = raw
    return _validate_manual_box(box), name


# --- Entry point 1: detect ------------------------------------------------------

def run_photo_detect(
    db: Session,
    user_id: UUID,
    images: List[SanitizedImage],
    *,
    provider=None,
    detect=None,
) -> List[PhotoDetectOutcome]:
    """Detect garments in each photo and persist the regions in transient sessions.

    READ-ONLY against the ledgers: no ProcessedUpload, no IngestRun, no cutouts, no
    storage writes. A duplicate photo (exact sha256 or near-dup phash vs
    processed_uploads) gets NO session and NO Gemini call. Multi-person photos flow
    through — the user disambiguates by selecting regions (person_count is surfaced).

    Detecting the same still-pending photo twice UPSERTS the session (one row per
    (user, sha256) pending photo) and refreshes its TTL. Returns per-photo outcomes
    in input order; region dicts carry no masks.
    """
    # Resolve at call time (not as a default arg) so tests can monkeypatch the module
    # symbol on the route path that doesn't pass `detect` explicitly.
    if detect is None:
        detect = detect_garments_with_regions

    # Opportunistic sweep: this user's expired, never-committed sessions.
    db.query(PhotoDetectSession).filter(
        PhotoDetectSession.user_id == user_id,
        PhotoDetectSession.status == "pending",
        PhotoDetectSession.expires_at < _utc_now(),
    ).delete(synchronize_session=False)
    db.commit()

    # Pass 1 (serial, cheap DB reads): flag duplicates. A dup gets NO Gemini call and
    # NO session — unchanged.
    is_dup = [_is_duplicate_upload(db, user_id, s) for s in images]

    # Pass 2 (concurrent): the per-photo Gemini detection is the dominant latency and does
    # NO DB writes, so fan the non-duplicate photos out over a BOUNDED pool. There is no
    # shared mutable state (each future returns its own DetectionResult), so nothing races.
    # detect_garments_with_regions never raises (empty result on model/parse failure), so
    # one bad photo can't fail the batch.
    detections: Dict[int, DetectionResult] = {}
    to_detect = [(i, s) for i, s in enumerate(images) if not is_dup[i]]
    if to_detect:
        cap = max(1, int(settings.PHOTO_DETECT_MAX_CONCURRENCY))
        workers = min(cap, len(to_detect))
        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="photodetect"
        ) as pool:
            futures = {
                pool.submit(
                    detect, image_bytes=s.data, content_type=s.content_type,
                    provider=provider,
                ): i
                for (i, s) in to_detect
            }
            for fut in futures:
                detections[futures[fut]] = fut.result()

    # Pass 3 (serial, on the request session): persist each detect session in INPUT ORDER.
    # All DB writes stay on the one session, so the (user, sha256, pending) upsert +
    # idempotency + dup handling are identical to the serial version (even two identical
    # photos in one batch collapse to one refreshed row, exactly as before).
    outcomes: List[PhotoDetectOutcome] = []
    for i, sanitized in enumerate(images):
        if is_dup[i]:
            outcomes.append(PhotoDetectOutcome(
                session_id=None, image_sha256=sanitized.sha256,
                width=sanitized.width, height=sanitized.height,
                duplicate=True, person_count=0, regions=[],
            ))
            continue

        detection = detections[i]
        regions = [
            _region_json(idx, garment)
            for idx, garment in enumerate(detection.garments)
        ]
        expires_at = _utc_now() + timedelta(hours=settings.PHOTO_SESSION_TTL_HOURS)

        # Upsert on (user, sha256, pending): re-detecting a photo the user hasn't
        # committed yet refreshes the ONE session instead of piling up rows.
        session = (
            db.query(PhotoDetectSession)
            .filter(
                PhotoDetectSession.user_id == user_id,
                PhotoDetectSession.image_sha256 == sanitized.sha256,
                PhotoDetectSession.status == "pending",
            )
            .first()
        )
        if session is not None:
            session.phash = sanitized.phash
            session.width = sanitized.width
            session.height = sanitized.height
            session.person_count = detection.person_count
            session.regions = regions
            session.expires_at = expires_at
        else:
            session = PhotoDetectSession(
                user_id=user_id,
                image_sha256=sanitized.sha256,
                phash=sanitized.phash,
                width=sanitized.width,
                height=sanitized.height,
                person_count=detection.person_count,
                regions=regions,
                status="pending",
                expires_at=expires_at,
            )
            db.add(session)
        db.commit()

        outcomes.append(PhotoDetectOutcome(
            session_id=str(session.id), image_sha256=sanitized.sha256,
            width=sanitized.width, height=sanitized.height,
            duplicate=False, person_count=detection.person_count,
            regions=[_region_public(r) for r in regions],
        ))

    logger.info(
        "photo detect user=%s: photos=%d sessions=%d dup=%d regions=%d",
        user_id, len(images),
        sum(1 for o in outcomes if o.session_id is not None),
        sum(1 for o in outcomes if o.duplicate),
        sum(len(o.regions) for o in outcomes),
    )
    return outcomes


# --- Entry point 2: commit ------------------------------------------------------

def _load_session_for_commit(
    db: Session, user_id: UUID, selection: PhotoSelection,
) -> PhotoDetectSession:
    """Load + validate one selection's session. Raises the commit error taxonomy."""
    try:
        session_uuid = UUID(str(selection.session_id))
    except (ValueError, AttributeError, TypeError):
        raise PhotoSessionNotFound("unknown session")

    session = (
        db.query(PhotoDetectSession)
        .filter(
            PhotoDetectSession.id == session_uuid,
            PhotoDetectSession.user_id == user_id,  # foreign sessions look absent
        )
        .first()
    )
    if session is None:
        raise PhotoSessionNotFound("unknown session")
    if session.status == "committed":
        raise PhotoSessionConflict("session already committed")
    if session.status == "expired" or _as_utc(session.expires_at) < _utc_now():
        raise PhotoSessionExpired("session expired; run detect again")

    known_ids = {r.get("region_id") for r in (session.regions or [])}
    unknown = [rid for rid in selection.selected_region_ids if rid not in known_ids]
    if unknown:
        raise PhotoSelectionInvalid("unknown region id(s) for session")

    if len(selection.manual_boxes) > MAX_MANUAL_BOXES_PER_PHOTO:
        raise PhotoSelectionInvalid(
            f"too many manual boxes (max {MAX_MANUAL_BOXES_PER_PHOTO} per photo)")
    for raw_box in selection.manual_boxes:
        _parse_manual_box(raw_box)  # validates geometry + optional name shape
    return session


def run_photo_commit(
    db: Session,
    user_id: UUID,
    storage_client,
    sanitized_by_sha: Dict[str, SanitizedImage],
    selections: List[PhotoSelection],
    *,
    provider=None,
    describe=None,
    defer_completion: bool = False,
    generation_available: bool = True,
) -> PhotoCommitResult:
    """Stage the user's SELECTED regions (+ manual boxes) from re-uploaded photos.

    ``sanitized_by_sha`` maps sha256(original bytes) -> SanitizedImage for the files
    re-received by the commit request; each selection's session binds to its file by
    session.image_sha256. All selections are validated BEFORE anything is written, so
    a 4xx never leaves partial state. This is the step that writes ingest_runs and
    (for photos that staged >= 1 item) processed_uploads; a zero-selection photo
    skips the ledger so it stays re-detectable.

    G2 PER-ZONE ACCOUNTING (Photo-seam Phase 3): every selected zone deterministically
    becomes a candidate or an explicit count — selected == staged + failed + zones in
    duplicate photos. A zone whose cutout can't be built is staged as a TERMINAL
    'failed' candidate (traceable by source_line_key, visible in settle accounting) —
    never silently dropped.

    ``generation_available=False`` (generation unarmed / storage down): a compliant
    product card can NEVER be produced, so zones are staged terminal-'failed' rather
    than left permanently unsettled — the batch settles immediately and honestly.
    Their photos skip the processed_uploads ledger, so re-uploading after generation
    is configured re-stages the same source_line_keys cleanly.
    """
    if describe is None:
        describe = describe_garment_crop

    # ---- Validation pass: raise before creating the run / staging anything. ----
    seen_session_ids = set()
    loaded: List[tuple] = []
    for selection in selections:
        session = _load_session_for_commit(db, user_id, selection)
        if session.id in seen_session_ids:
            raise PhotoSelectionInvalid("duplicate session in selections")
        seen_session_ids.add(session.id)
        if session.image_sha256 not in sanitized_by_sha:
            raise PhotoSessionConflict(
                "no uploaded file matches this session's photo")
        loaded.append((selection, session))

    # ---- Staging pass -----------------------------------------------------------
    sync_id = uuid4()
    run = IngestRun(sync_id=sync_id, user_id=user_id, status="running",
                    source_type="photo")
    db.add(run)
    db.commit()

    result = PhotoCommitResult(sync_id=str(sync_id))
    # Stage-time canonicalize-lite: one facts load per commit feeds every staged
    # candidate's size default (the shared readiness invariant needs size-or-sizeless).
    facts = load_user_facts(db, user_id)
    try:
        for selection, session in loaded:
            sanitized = sanitized_by_sha[session.image_sha256]
            # G2 accounting: EVERY requested zone is counted up front, so
            # selected == staged + failed + zones inside duplicate photos, always.
            result.selected += len(selection.selected_region_ids) + len(selection.manual_boxes)

            # Exact-dup re-check: the same photo may have been committed by another
            # request since detect ran. Count it, retire the session, stage nothing.
            already = (
                db.query(ProcessedUpload.id)
                .filter(
                    ProcessedUpload.user_id == user_id,
                    ProcessedUpload.image_sha256 == session.image_sha256,
                )
                .first()
            )
            if already is not None:
                session.status = "committed"
                db.commit()
                result.duplicates += 1
                continue

            original = Image.open(io.BytesIO(sanitized.data))
            regions_by_id = {
                r.get("region_id"): r for r in (session.regions or [])
            }
            staged_here = 0
            on_model = session.person_count >= 1

            def _stage_zone(garment_like, image_url, slk) -> None:
                """Stage ONE zone with full G2 accounting — a candidate ALWAYS exists.

                Terminal-'failed' (visible, traceable by source_line_key, settles the
                batch) when the cutout is unusable (image_url None) or generation is
                unavailable (a compliant card can never be produced). Otherwise a
                viable pending candidate. A re-staged zone whose prior candidate holds
                a verified ready card keeps it (terminal states never regress)."""
                nonlocal staged_here
                cand = _stage_candidate(
                    db, user_id, sync_id, garment_like, image_url, slk,
                    on_model=on_model, facts=facts,
                )
                db.flush()  # assign cand.id before the dedup seam inspects it
                # Wired dedup seam (currently a no-op 'unique' stub). The real matcher
                # and any generation gating hang off this without a pipeline change.
                dedup_check(db, user_id, cand)
                if cand.pipeline_state in TERMINAL_STATES:
                    staged_here += 1  # re-staged, already-ready card stays viable
                    return
                if image_url is None or not generation_available:
                    cand.pipeline_state = "failed"
                    cand.generation_status = "failed"
                    cand.image_status = "placeholder"
                    result.failed += 1
                    logger.info(
                        "photo commit: zone terminal-failed user=%s sync=%s reason=%s",
                        user_id, sync_id,
                        "no_cutout" if image_url is None else "generation_unavailable",
                    )
                    return
                staged_here += 1

            # (a) Selected detected regions — cutout with the session's stored mask.
            for rid in selection.selected_region_ids:
                garment = GarmentRegion.model_validate(regions_by_id[rid])
                slk = _source_line_key(session.image_sha256, garment.box_2d)
                cut = build_cutout(
                    original=original, box_2d=garment.box_2d, mask_b64=garment.mask,
                )
                # G6: an on-model source photo (person visible) yields cutouts that contain a
                # person — flag them so the crop is never displayed, only used as the gen ref.
                # G2: an unusable box stages a TERMINAL 'failed' candidate (image_url None)
                # instead of silently dropping the zone.
                image_url = store_cutout(storage_client, user_id, cut) if cut else None
                _stage_zone(garment, image_url, slk)

            # (b) User-drawn manual boxes — box crop, then describe the crop. A user-typed
            #     name is fed to the SAME single-crop extraction as a HINT (not used
            #     verbatim), so a named region yields a clean canonical title + typed
            #     attributes with confidence — like a detected garment — and the label
            #     merely steers it. Provenance stays 'extracted' at confirm (the hint is a
            #     seed, never a user_edited lock). Near-zero marginal cost: the describe
            #     call already runs for unnamed boxes.
            for raw_box in selection.manual_boxes:
                box, manual_name = _parse_manual_box(raw_box)
                slk = _source_line_key(session.image_sha256, box)
                cut = build_cutout(original=original, box_2d=box, mask_b64=None)
                described = (
                    describe(cut.data, cut.content_type, hint=manual_name, provider=provider)
                    if cut is not None
                    else None
                )
                if described is None:
                    # Model failed (or no cutout to describe). If the user typed a name,
                    # keep it (low confidence) so their input is never lost; otherwise a
                    # neutral placeholder. Editable in the deck either way.
                    described = GarmentDescription(
                        name=manual_name or "Item",
                        category=GarmentCategory.other,
                        confidence_overall=0.3 if manual_name else 0.2,
                    )
                image_url = store_cutout(storage_client, user_id, cut) if cut else None
                _stage_zone(described, image_url, slk)

            # Ledger only when something was staged: a zero-selection photo leaves
            # no processed_uploads row, so the user can re-detect it later.
            if staged_here > 0:
                db.add(ProcessedUpload(
                    user_id=user_id, sync_id=sync_id,
                    image_sha256=session.image_sha256, phash=session.phash,
                    status="processed", item_count=staged_here,
                ))
            session.status = "committed"
            db.commit()
            result.images_processed += 1
            result.staged += staged_here

        run.extracted_count = result.staged
        if defer_completion and result.staged > 0:
            # Generation will run in the background and OWNS finalization: the run stays
            # 'running' so GET /ingest/status reports generation-in-flight, and
            # generation_service._finalize_run flips it to 'completed' when done.
            run.status = "running"
        else:
            run.status = "completed"
            run.finished_at = _utc_now()
        db.commit()
    except Exception:
        db.rollback()
        run.status = "error"
        run.finished_at = _utc_now()
        db.commit()
        raise

    logger.info(
        "photo commit user=%s sync=%s: processed=%d dup=%d selected=%d staged=%d failed=%d",
        user_id, sync_id, result.images_processed, result.duplicates,
        result.selected, result.staged, result.failed,
    )
    return result
