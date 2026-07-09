"""Chat image → closet ingest bridge (Wave S3e).

When a user sends a garment photo in chat and asks the stylist to add it, the
``add_photo_to_closet`` tool routes the ALREADY-sanitized chat image into the
SAME photo-ingest spine the ``/photo/ingest/*`` HTTP routes use —
``run_photo_detect`` then ``run_photo_commit`` — with no HTTP round-trip and no
re-implementation of staging.

The chat image is auto-selected in FULL: every garment the detector finds is
staged (the user already said "yes, add them"). Per-item accept/reject happens
later in the SHARED review deck (GET /gmail/ingest/candidates → POST
/gmail/ingest/confirm), exactly as for a photo upload. The handoff returns the
``sync_id`` so chat can surface a "ready for review" button deep-linking to
``/review?sync_id=…``.

SESSION MODEL — this runs on its OWN owner session (``SessionLocal``),
user-scoped by the explicit server-derived ``user_id`` plus the spine's
app-level ``WHERE user_id`` filters — IDENTICAL to the photo-ingest route
(``Depends(get_db)``). It deliberately does NOT reuse the chat turn's RLS-scoped
connection: ``run_photo_detect``/``run_photo_commit`` own their transaction
boundaries (several ``db.commit()`` calls each), which the single per-turn chat
transaction must not absorb.

INCOGNITO — never reached in incognito: the tool short-circuits before calling
here, so no detect session, cutout, storage upload, or candidate row is ever
written (the chat zero-trace guarantee is preserved).

DEDUP — no bespoke pre-check. The spine already skips a re-uploaded photo
(exact sha256 / near-dup phash vs processed_uploads) at detect, and collapses a
re-detected garment onto its existing closet row via UNIQUE(user_id,
source_line_key) at confirm. A garment already in the closet is handled by that
confirm-time dedup, not here.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from app.photo_closet.ingest_service import (
    PhotoSelection,
    run_photo_commit,
    run_photo_detect,
)
from app.services.stylist.tools import ImageAttachment
from app.utils.image_validation import validate_and_sanitize

logger = logging.getLogger(__name__)


@dataclass
class IngestHandoff:
    """Result of routing one chat photo into the ingest spine.

    ``added`` False carries a machine ``reason`` the tool maps to honest copy:
      * ``duplicate``      — the photo was already ingested (spine skipped it).
      * ``no_garments``    — the detector found nothing to add.
      * ``nothing_staged`` — regions existed but none produced a usable cutout.
    """

    added: bool
    sync_id: Optional[str] = None
    staged: int = 0
    duplicates: int = 0
    reason: Optional[str] = None


def _storage_client():
    """Best-effort storage client, mirroring the photo-ingest route: a missing
    bucket stages candidates without images rather than failing the add."""
    try:
        from app.utils.supabase_storage import SupabaseStorageClient

        return SupabaseStorageClient.from_env()
    except Exception as exc:  # missing S3 env / client init failure
        logger.warning(
            "chat→closet: storage unavailable, staging without images: %s",
            type(exc).__name__,
        )
        return None


def add_chat_photo_to_closet(user_id: UUID, image: ImageAttachment) -> IngestHandoff:
    """Detect + stage every garment in one sanitized chat photo for review.

    Runs on its own owner ``SessionLocal`` (see module docstring). Best-effort
    background generation is dispatched only when it can complete (storage +
    provider armed), exactly like the route; otherwise the run finalizes at
    commit with raw cutouts. Never called in incognito.
    """
    from app.db import SessionLocal
    from app.photo_closet.generation_service import generate_background, generation_armed

    # The chat attachment was sanitized once on the way in; reuse that
    # SanitizedImage (true original-bytes sha256 → best dedup) and only
    # re-sanitize if a caller built the attachment without it.
    sanitized = image.sanitized or validate_and_sanitize(image.data)

    db = SessionLocal()
    try:
        outcome = run_photo_detect(db, user_id, [sanitized])[0]
        if outcome.duplicate:
            return IngestHandoff(added=False, reason="duplicate")
        if not outcome.session_id or not outcome.regions:
            return IngestHandoff(added=False, reason="no_garments")

        # Auto-select everything the detector found — the user already consented
        # to adding "these"; the review deck is where they prune.
        selection = PhotoSelection(
            session_id=outcome.session_id,
            selected_region_ids=[int(r["region_id"]) for r in outcome.regions],
        )

        storage_client = _storage_client()
        will_generate = storage_client is not None and generation_armed()

        result = run_photo_commit(
            db,
            user_id,
            storage_client,
            {sanitized.sha256: sanitized},
            [selection],
            defer_completion=will_generate,
            generation_available=will_generate,
        )

        if result.staged == 0:
            reason = "duplicate" if result.duplicates else "nothing_staged"
            return IngestHandoff(added=False, reason=reason, duplicates=result.duplicates)

        # Background generation owns run finalization when deferred. We are already
        # off the request thread (SSE worker), so a daemon thread with its OWN
        # session mirrors the route's BackgroundTasks dispatch (same pattern chat
        # uses for post-turn distillation). Never raises into the turn.
        if will_generate:
            threading.Thread(
                target=generate_background,
                args=(str(user_id), result.sync_id),
                daemon=True,
            ).start()

        logger.info(
            "chat→closet user=%s sync=%s staged=%d dup=%d",
            user_id, result.sync_id, result.staged, result.duplicates,
        )
        return IngestHandoff(
            added=True,
            sync_id=result.sync_id,
            staged=result.staged,
            duplicates=result.duplicates,
        )
    finally:
        db.close()
