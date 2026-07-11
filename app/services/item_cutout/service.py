"""Item-cutout orchestration (Collage Phase 1): matte ONCE at image-birth,
store the true-alpha cutout, stamp the row — so the collage never has to derive
a cutout at render time again.

Root cause this kills (Phase-0 spike): the collage re-keyed every item's JPEG
per render with a color-tolerance flood fill, which structurally cannot
separate white/light garments from the near-white background — bites out of
light jeans, dissolved white tees, shadow smudges, opaque-rectangle fallbacks.
The matte here is computed once per ITEM (birth or backfill), locally (u2net
ONNX on CPU, no generation API, $0 marginal, off-cap), QA-gated, and stored;
Phase 2 rewrites the compositor to consume the stored alpha.

FLOW per item (matte_item):
  display_image_url  ->  download  ->  u2net matte  ->  QA gate  ->
    pass: PNG -> content-addressed item_cutouts/{user_id}/ upload,
          cutout_url + cutout_status='ready'
    fail: cutout_status='no_matte' (collage renders the item FLAT on its own
          tile — NEVER a patchy rectangle), cutout_url stays NULL

INVARIANTS
  * The source is display_image_url — THE fail-closed display gate. A masked
    item (person_status unknown/person_present, un-verified photo crop, …)
    yields None and is SKIPPED: a person is never matted into a cutout, and a
    raw crop never becomes one. Skipped = cutout_status stays NULL, so the item
    remains a backfill target for after its card heals.
  * Best-effort, never raises into a caller: a matting failure can not block an
    item's birth, a confirm response, or a backfill sweep over other items.
  * Privacy: cutouts are personal images. Stored per-user
    (item_cutouts/{user_id}/, same posture as generated_items/); logs carry
    ids + counts + QA reasons only, never bytes or URLs. There is NO cross-user
    cutout cache — the content-addressed dedup (image_blobs) only collapses
    byte-identical uploads, exactly as it already does for every stored image.
  * Off the hot path: the birth hook runs as a Starlette background task after
    the confirm response; the model session is a process-lazy singleton (see
    engine.py for the deploy shape).
"""
from __future__ import annotations

import io
import logging
from typing import List, Optional
from uuid import UUID

from PIL import Image
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import ClothingItem
from app.models.closet import display_image_url

# Reused download seam (module attr so tests monkeypatch service._download),
# same pattern as the stylist collage.
from app.photo_closet.generation_service import _download_bytes as _download

from app.services.item_cutout import engine
from app.services.item_cutout.qa import qa_matte

logger = logging.getLogger(__name__)

# The matting seam tests monkeypatch: image in, RGBA out (or None on failure).
matte_rgba = engine.matte

# cutout_status vocabulary (CHECK in migration 0042):
#   NULL       -> never matted (backfill target)
#   'ready'    -> cutout_url holds the stored true-alpha PNG
#   'no_matte' -> matte was produced but the QA gate refused it; render flat
STATUS_READY = "ready"
STATUS_NO_MATTE = "no_matte"


def _store_cutout(user_id: UUID, png: bytes) -> Optional[str]:
    """Upload cutout bytes exactly like every other derived image: through the
    image_blobs dedup, into a per-user folder. None when storage is missing."""
    try:
        from app.utils.supabase_storage import SupabaseStorageClient

        storage = SupabaseStorageClient.from_env()
    except Exception as exc:  # missing S3 env / client init failure
        logger.warning("cutout: storage unavailable (%s)", type(exc).__name__)
        return None
    from app.utils.image_blob_store import get_or_upload

    return get_or_upload(
        png,
        lambda: storage.upload_bytes(
            png,
            folder=f"item_cutouts/{user_id}",
            content_type="image/png",
            suffix=".png",
        ),
    )


def matte_item(db: Session, item: ClothingItem) -> str:
    """Matte + store + stamp ONE item. Returns the disposition for counting:
    'ready' | 'no_matte' | 'skipped'. Mutates the row but does NOT commit —
    the caller owns transaction boundaries (backfill commits per item so a
    kill mid-sweep loses at most one matte).

    'skipped' (cutout_status left NULL — still a backfill target) covers: the
    kill-switch, no displayable image, download/decode failure, model
    unavailable, storage unavailable. Only an actual QA refusal writes the
    terminal 'no_matte'.
    """
    if not settings.CUTOUT_MATTING_ENABLED:
        return "skipped"

    url = display_image_url(item)
    if not url:
        return "skipped"  # masked / no card yet: never matte what we can't display

    fetched = _download(url)
    if fetched is None:
        return "skipped"
    try:
        img = Image.open(io.BytesIO(fetched[0]))
        img.load()
    except Exception:
        logger.info("cutout: undecodable display image (item=%s)", item.id)
        return "skipped"

    rgba = matte_rgba(img)
    if rgba is None:
        return "skipped"  # runtime/model unavailable — leave for backfill

    verdict = qa_matte(rgba)
    if not verdict.ok:
        item.cutout_status = STATUS_NO_MATTE
        item.cutout_url = None
        logger.info("cutout: no_matte (item=%s reason=%s)", item.id, verdict.reason)
        return STATUS_NO_MATTE

    buf = io.BytesIO()
    rgba.save(buf, format="PNG", optimize=True)
    stored = _store_cutout(item.user_id, buf.getvalue())
    if stored is None:
        return "skipped"  # storage hiccup: retryable, don't burn a terminal state

    item.cutout_url = stored
    item.cutout_status = STATUS_READY
    logger.info("cutout: ready (item=%s)", item.id)
    return STATUS_READY


def matte_items_background(user_id_str: str, item_id_strs: List[str]) -> None:
    """THE BIRTH HOOK. FastAPI BackgroundTask behind the confirm route (and
    called inline by the manual auto-confirm, which already runs in a background
    generation pass) — every path through THE confirm chokepoint schedules this
    for its newly-written items. ⚠️ IN-PROCESS (Starlette threadpool), runs
    after the response is sent; opens its OWN session (the request session is
    closed by now). Best-effort: any failure is logged, never propagated —
    un-matted items stay NULL and the backfill sweep picks them up.
    """
    if not item_id_strs or not settings.CUTOUT_MATTING_ENABLED:
        return
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        user_id = UUID(user_id_str)
        item_ids = [UUID(s) for s in item_id_strs]
        # Scope to the caller's own items (defense-in-depth; ids come from our own write).
        items = (
            db.query(ClothingItem)
            .filter(ClothingItem.user_id == user_id, ClothingItem.id.in_(item_ids))
            .all()
        )
        counts = {"ready": 0, "no_matte": 0, "skipped": 0}
        for item in items:
            if item.cutout_status == STATUS_READY and item.cutout_url:
                continue  # re-confirm of an already-matted row: nothing to do
            outcome = matte_item(db, item)
            counts[outcome] += 1
            db.commit()  # per item: a crash mid-batch keeps earlier mattes
        logger.info(
            "cutout birth-hook user=%s: items=%d ready=%d no_matte=%d skipped=%d",
            user_id, len(items), counts["ready"], counts["no_matte"], counts["skipped"],
        )
    except Exception as exc:
        logger.error(
            "matte_items_background: unhandled error — %s: %s", type(exc).__name__, exc
        )
        db.rollback()
    finally:
        db.close()
