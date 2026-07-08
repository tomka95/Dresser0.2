"""Content-addressed upload (P3.7 split of the image_resolver god-module).

Single upload chokepoint for every tier — the inline -> email-img -> cache ->
og:image waterfall order in resolve.py is unaffected by which tier calls this.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID


@dataclass
class _Stored:
    """An uploaded (or dedup-reused) blob: its storage URL + content hash.

    Carried through the run-scoped cache so a cache hit on the same source still
    yields the sha needed to stage a product_image_cache row.
    """
    url: str
    sha: str


def _upload(storage_client, user_id: UUID, raw: bytes, suffix: str, content_type: str) -> Optional[_Stored]:
    if storage_client is None:
        return None
    # Content-addressed dedup: identical bytes (this run, a prior run, or any user)
    # reuse the existing stored URL instead of uploading a fresh blob — stops the
    # orphaned-blob accumulation. The actual PUT is deferred to the callable and
    # runs at most once per distinct image. Single upload chokepoint for all tiers,
    # so the inline -> email-img -> cache -> og:image waterfall order is unchanged.
    from app.utils.image_blob_store import get_or_upload, sha256_hex

    url = get_or_upload(
        raw,
        lambda: storage_client.upload_bytes(
            raw,
            folder=f"ingest_items/{user_id}",
            content_type=content_type,
            suffix=suffix,
        ),
    )
    if not url:
        return None
    return _Stored(url=url, sha=sha256_hex(raw))
