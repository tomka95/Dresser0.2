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
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from uuid import UUID, uuid4

from PIL import Image
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import IngestCandidate, IngestRun, PhotoDetectSession, ProcessedUpload
from app.photo_closet.cutout import build_cutout
from app.photo_closet.dedup import dedup_check
from app.photo_closet.detection import (
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
    manual_boxes: List[List[int]] = field(default_factory=list)


@dataclass
class PhotoCommitResult:
    sync_id: str
    images_processed: int = 0   # photos whose selection was staged (dups excluded)
    staged: int = 0             # candidates staged across all photos
    duplicates: int = 0         # photos skipped: already committed elsewhere


# --- Shared helpers (unchanged from Wave 1) ------------------------------------

def store_cutout(storage_client, user_id: UUID, cut) -> Optional[str]:
    """Upload one cutout via the content-addressed image_blobs dedup; return its URL.

    Module-level so tests can monkeypatch it without a real bucket. Mirrors
    image_resolver._upload: identical bytes (any run, any user) reuse one stored URL.
    """
    if storage_client is None:
        return None
    from app.utils.image_blob_store import get_or_upload

    return get_or_upload(
        cut.data,
        lambda: storage_client.upload_bytes(
            cut.data,
            folder=f"photo_items/{user_id}",
            content_type=cut.content_type,
            suffix=cut.suffix,
        ),
    )


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
    source_line_key: str,
) -> IngestCandidate:
    """Upsert one garment as a pending photo candidate on UNIQUE(user_id, source_line_key).

    ``garment`` is any GarmentRegion-shaped object (GarmentRegion or
    GarmentDescription). Dialect-agnostic (select-then-insert/update) so it runs on
    SQLite + Postgres alike.
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
    fields = dict(
        sync_id=sync_id,
        message_id=None,
        source_message_ids=[],
        seen_count=1,
        name=garment.name,
        brand=garment.brand,
        category=garment.category.value,
        color=garment.color,
        size=None,
        image_url=image_url,
        image_status="user_uploaded",
        source_type="photo",
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
        for k, v in fields.items():
            setattr(existing, k, v)
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

    outcomes: List[PhotoDetectOutcome] = []
    for sanitized in images:
        if _is_duplicate_upload(db, user_id, sanitized):
            outcomes.append(PhotoDetectOutcome(
                session_id=None, image_sha256=sanitized.sha256,
                width=sanitized.width, height=sanitized.height,
                duplicate=True, person_count=0, regions=[],
            ))
            continue

        detection = detect(
            image_bytes=sanitized.data,
            content_type=sanitized.content_type,
            provider=provider,
        )
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
    for box in selection.manual_boxes:
        _validate_manual_box(box)
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
) -> PhotoCommitResult:
    """Stage the user's SELECTED regions (+ manual boxes) from re-uploaded photos.

    ``sanitized_by_sha`` maps sha256(original bytes) -> SanitizedImage for the files
    re-received by the commit request; each selection's session binds to its file by
    session.image_sha256. All selections are validated BEFORE anything is written, so
    a 4xx never leaves partial state. This is the step that writes ingest_runs and
    (for photos that staged >= 1 item) processed_uploads; a zero-selection photo
    skips the ledger so it stays re-detectable.
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
    try:
        for selection, session in loaded:
            sanitized = sanitized_by_sha[session.image_sha256]

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

            # (a) Selected detected regions — cutout with the session's stored mask.
            for rid in selection.selected_region_ids:
                garment = GarmentRegion.model_validate(regions_by_id[rid])
                cut = build_cutout(
                    original=original, box_2d=garment.box_2d, mask_b64=garment.mask,
                )
                if cut is None:
                    continue  # unusable box -> skip this garment
                image_url = store_cutout(storage_client, user_id, cut)
                slk = _source_line_key(session.image_sha256, garment.box_2d)
                cand = _stage_candidate(db, user_id, sync_id, garment, image_url, slk)
                db.flush()  # assign cand.id before the dedup seam inspects it
                # Wired dedup seam (currently a no-op 'unique' stub). The real matcher
                # and any generation gating hang off this without a pipeline change.
                dedup_check(db, user_id, cand)
                staged_here += 1

            # (b) User-drawn manual boxes — box crop, then describe the crop.
            for raw_box in selection.manual_boxes:
                box = _validate_manual_box(raw_box)
                cut = build_cutout(original=original, box_2d=box, mask_b64=None)
                if cut is None:
                    continue
                described = describe(cut.data, cut.content_type, provider=provider)
                if described is None:
                    # Model failed: stage a low-confidence placeholder the user can
                    # edit in the deck rather than dropping their selection.
                    described = GarmentDescription(
                        name="Item", category=GarmentCategory.other,
                        confidence_overall=0.2,
                    )
                image_url = store_cutout(storage_client, user_id, cut)
                slk = _source_line_key(session.image_sha256, box)
                cand = _stage_candidate(
                    db, user_id, sync_id, described, image_url, slk)
                db.flush()
                dedup_check(db, user_id, cand)
                staged_here += 1

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

        run.status = "completed"
        run.extracted_count = result.staged
        run.finished_at = _utc_now()
        db.commit()
    except Exception:
        db.rollback()
        run.status = "error"
        run.finished_at = _utc_now()
        db.commit()
        raise

    logger.info(
        "photo commit user=%s sync=%s: processed=%d dup=%d staged=%d",
        user_id, sync_id, result.images_processed, result.duplicates, result.staged,
    )
    return result
