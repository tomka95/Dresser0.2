"""Durable, content-addressed dedup for stored images (Wave 0 image system).

THE PROBLEM
-----------
The resolver uploaded a fresh ``uuid4`` object to Supabase storage on every run,
so re-resolving / backfilling the same image produced a new blob each time and the
old ones became orphans. The run-scoped ResolvedImageCache (image_resolver.py) only
dedups by SOURCE url/cid WITHIN a single run; it cannot stop cross-run duplication.

THE FIX
-------
Before uploading bytes we hash them (sha256) and look them up in ``image_blobs``.
If those exact bytes were already stored — this run, a prior run, or for any user —
we reuse the recorded URL and skip the upload entirely.

RACE-SAFETY
-----------
The table PK is the content hash. Two concurrent uploaders of the SAME bytes both
PUT to storage, but only one ``image_blobs`` row wins (INSERT ... ON CONFLICT DO
NOTHING); the loser re-reads and converges on the winner's URL, so every caller
ends up pointing at ONE url. The loser's freshly-PUT object is the only (rare)
orphan, bounded to a single concurrent window per distinct image.

THREADING
---------
``get_or_upload`` is called from resolver WORKER threads during extraction. It
opens its OWN short-lived Session (never the run's session, which is not shared
across threads) and closes it immediately. The engine connection pool is
thread-safe, so a per-call session is the correct pattern here.

Wave 2a EXTENDS image_blobs (additive columns) rather than replacing it.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Callable, Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = logging.getLogger(__name__)


def sha256_hex(data: bytes) -> str:
    """Lowercase hex sha256 of ``data`` — the image_blobs primary key."""
    return hashlib.sha256(data).hexdigest()


def get_or_upload(raw: bytes, upload: Callable[[], Optional[str]]) -> Optional[str]:
    """Return the stored URL for ``raw``, invoking ``upload`` only on a cache miss.

    ``upload`` is an already-bound callable that PUTs the bytes to storage and
    returns the public URL (or None if storage is unavailable). It runs AT MOST
    ONCE per distinct content hash across the whole deployment. On a hit, the
    recorded URL is returned and ``upload`` is never called.

    Returns None only when storage is unavailable (``upload`` returned None) — the
    resolver treats that exactly as it did before (no image recorded).
    """
    sha = sha256_hex(raw)

    # Late imports: avoid an import cycle (image_resolver -> this -> models/db) and
    # keep the module importable in contexts that never touch the DB.
    from app.db import SessionLocal
    from app.models import ImageBlob

    db = SessionLocal()
    try:
        existing = (
            db.query(ImageBlob)
            .filter(ImageBlob.content_sha256 == sha)
            .first()
        )
        if existing is not None:
            return existing.image_url

        url = upload()
        if not url:
            return None  # storage unavailable — nothing to record or dedup

        # Record the mapping; if a concurrent uploader already inserted this hash,
        # keep theirs (DO NOTHING) and converge on it below.
        db.execute(
            pg_insert(ImageBlob.__table__)
            .values(content_sha256=sha, image_url=url)
            .on_conflict_do_nothing(index_elements=["content_sha256"])
        )
        db.commit()

        winner = (
            db.query(ImageBlob)
            .filter(ImageBlob.content_sha256 == sha)
            .first()
        )
        # winner is normally present; fall back to our own url defensively.
        return winner.image_url if winner is not None else url
    finally:
        db.close()


def delete_by_url(url: str) -> int:
    """Drop the dedup mapping(s) for a purged blob (Photo-seam Phase 5). Never raises.

    Without this, re-uploading the same bytes after a purge would 'dedup' onto the
    DELETED storage object and record a dead URL. Own short-lived session (same
    threading rationale as get_or_upload). Returns rows removed."""
    if not url:
        return 0
    from app.db import SessionLocal
    from app.models import ImageBlob

    db = SessionLocal()
    try:
        n = (
            db.query(ImageBlob)
            .filter(ImageBlob.image_url == url)
            .delete(synchronize_session=False)
        )
        db.commit()
        return int(n or 0)
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return 0
    finally:
        db.close()
