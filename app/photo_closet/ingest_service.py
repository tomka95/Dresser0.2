"""Photo -> closet ingest orchestrator (Wave 1).

Per uploaded photo: idempotency check -> detect garments -> (hold if >1 person) ->
cut out each garment -> stage an ingest_candidate. The candidates then flow through
the SAME GET /…/candidates deck and POST /…/confirm path as Gmail — this module never
writes clothing_items itself.

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
from datetime import datetime, timezone
from typing import Callable, List, Optional
from uuid import UUID, uuid4

from PIL import Image
from sqlalchemy.orm import Session

from app.models import IngestCandidate, IngestRun, ProcessedUpload
from app.photo_closet.cutout import build_cutout
from app.photo_closet.dedup import dedup_check
from app.photo_closet.detection import DetectionResult, detect_garments_with_regions
from app.utils.image_validation import SanitizedImage, phash_distance

logger = logging.getLogger(__name__)

# Near-duplicate threshold (Hamming distance over the 64-bit dHash). <= this and we
# treat a freshly-uploaded photo as a re-upload and skip the full detect+stage pass.
NEAR_DUP_DISTANCE = 6
# How many of a user's recent processed-upload phashes to scan for near-dups.
_NEAR_DUP_SCAN_LIMIT = 500


@dataclass
class PhotoIngestResult:
    sync_id: str
    images_processed: int = 0      # images that ran detect+stage
    held_multi_person: int = 0     # images skipped: >1 person (not guessed)
    duplicates: int = 0            # images skipped: exact or near duplicate
    staged: int = 0                # candidates staged across all images
    held_upload_shas: List[str] = field(default_factory=list)


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

    Dialect-agnostic (select-then-insert/update) so it runs on SQLite + Postgres alike.
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


def ingest_photos(
    db: Session,
    user_id: UUID,
    images: List[SanitizedImage],
    *,
    sync_id: Optional[UUID] = None,
    provider=None,
    storage_client=None,
    detect: Optional[Callable[..., DetectionResult]] = None,
) -> PhotoIngestResult:
    """Run validate-already-done images through detect -> crop -> stage.

    ``images`` are SanitizedImage (validated + EXIF-stripped by the route). Creates an
    ingest_runs row (source_type='photo') so /…/status works, and a processed_uploads
    row per image for idempotency. Returns counts; never writes clothing_items.
    """
    # Resolve at call time (not as a default arg) so tests can monkeypatch the module
    # symbol on the route path that doesn't pass `detect` explicitly.
    if detect is None:
        detect = detect_garments_with_regions

    sync_id = sync_id or uuid4()
    run = IngestRun(sync_id=sync_id, user_id=user_id, status="running", source_type="photo")
    db.add(run)
    db.commit()

    result = PhotoIngestResult(sync_id=str(sync_id))

    try:
        for sanitized in images:
            if _is_duplicate_upload(db, user_id, sanitized):
                result.duplicates += 1
                continue

            detection = detect(
                image_bytes=sanitized.data,
                content_type=sanitized.content_type,
                provider=provider,
            )

            # Privacy hold: more than one person -> do NOT guess which is the user.
            if detection.person_count > 1:
                db.add(ProcessedUpload(
                    user_id=user_id, sync_id=sync_id, image_sha256=sanitized.sha256,
                    phash=sanitized.phash, status="held_multi_person", item_count=0,
                ))
                db.commit()
                result.held_multi_person += 1
                result.held_upload_shas.append(sanitized.sha256)
                continue

            original = Image.open(io.BytesIO(sanitized.data))
            staged_here = 0
            for garment in detection.garments:
                cut = build_cutout(
                    original=original, box_2d=garment.box_2d, mask_b64=garment.mask,
                )
                if cut is None:
                    continue  # unusable box -> skip this garment
                image_url = store_cutout(storage_client, user_id, cut)
                slk = _source_line_key(sanitized.sha256, garment.box_2d)
                cand = _stage_candidate(
                    db, user_id, sync_id, garment, image_url, slk,
                )
                db.flush()  # assign cand.id before the dedup seam inspects it
                # Wired dedup seam (currently a no-op 'unique' stub). The real matcher
                # and any generation gating hang off this without a pipeline change.
                dedup_check(db, user_id, cand)
                staged_here += 1

            db.add(ProcessedUpload(
                user_id=user_id, sync_id=sync_id, image_sha256=sanitized.sha256,
                phash=sanitized.phash, status="processed", item_count=staged_here,
            ))
            db.commit()
            result.images_processed += 1
            result.staged += staged_here

        run.status = "completed"
        run.extracted_count = result.staged
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception:
        db.rollback()
        run.status = "error"
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        raise

    logger.info(
        "photo ingest user=%s sync=%s: processed=%d held_multi=%d dup=%d staged=%d",
        user_id, sync_id, result.images_processed, result.held_multi_person,
        result.duplicates, result.staged,
    )
    return result
