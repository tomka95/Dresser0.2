"""Gmail inline-image primitives (P3.7 split of the image_resolver god-module).

Trusted endpoint — the Gmail attachments API, NOT an outbound fetch of an
arbitrary URL from the email — so this concern carries no SSRF surface.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import httpx

from app.gmail_closet.fetch_service import _GMAIL_BASE

# Inline images smaller than this are almost certainly logos / spacers / tracking
# pixels, not product photos — skip them (mirrors the old extraction threshold).
_MIN_INLINE_BYTES = 4096


def suffix_for_mime(mime: str) -> Tuple[str, str]:
    """(suffix, content_type) for a Gmail part mime; defaults to png."""
    m = (mime or "").lower()
    if "png" in m:
        return ".png", "image/png"
    if "jpeg" in m or "jpg" in m:
        return ".jpg", "image/jpeg"
    if "webp" in m:
        return ".webp", "image/webp"
    if "gif" in m:
        return ".gif", "image/gif"
    return ".png", "image/png"


def get_attachment_bytes(
    client: httpx.Client, token: str, msg_id: str, attachment_id: str
) -> Optional[bytes]:
    """Fetch one attachment's bytes via the Gmail attachments API.

    This is the SAME trusted Gmail endpoint as the message fetch — NOT an outbound
    fetch of an arbitrary URL from the email, so it carries no SSRF surface.
    """
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = client.get(
            f"{_GMAIL_BASE}/messages/{msg_id}/attachments/{attachment_id}",
            headers=headers,
            params={"fields": "data,size"},
            timeout=30.0,
        )
        if resp.status_code != 200:
            return None
        data = resp.json().get("data")
        if not data:
            return None
        pad = "=" * ((4 - len(data) % 4) % 4)
        return base64.urlsafe_b64decode(data + pad)
    except Exception:
        return None


@dataclass
class _InlineImage:
    raw: bytes
    suffix: str
    content_type: str


def extract_inline_images(
    payload: dict, client: httpx.Client, token: str, msg_id: str
) -> Tuple[Dict[str, _InlineImage], List[_InlineImage]]:
    """Collect inline image parts, returning (by_content_id, ordered_list).

    ``by_content_id`` maps the part's Content-ID (with surrounding <>/cid: stripped)
    to its bytes, so an HTML ``<img src="cid:...">`` can be matched to its part.
    ``ordered_list`` is every qualifying inline image in document order (the fallback
    when the HTML carries no usable cid reference). Tiny images are dropped.
    """
    by_cid: Dict[str, _InlineImage] = {}
    ordered: List[_InlineImage] = []

    def _content_id(node: dict) -> Optional[str]:
        for h in node.get("headers", []) or []:
            if (h.get("name", "") or "").lower() == "content-id":
                return (h.get("value", "") or "").strip().strip("<>").strip()
        return None

    def _walk(node: dict) -> None:
        mime = node.get("mimeType", "") or ""
        body = node.get("body", {}) or {}
        if mime.lower().startswith("image/"):
            raw: Optional[bytes] = None
            data = body.get("data")
            attachment_id = body.get("attachmentId")
            if data:
                try:
                    pad = "=" * ((4 - len(data) % 4) % 4)
                    raw = base64.urlsafe_b64decode(data + pad)
                except Exception:
                    raw = None
            elif attachment_id:
                raw = get_attachment_bytes(client, token, msg_id, attachment_id)
            if raw and len(raw) >= _MIN_INLINE_BYTES:
                suffix, ctype = suffix_for_mime(mime)
                img = _InlineImage(raw=raw, suffix=suffix, content_type=ctype)
                ordered.append(img)
                cid = _content_id(node)
                if cid:
                    by_cid[cid] = img
        for part in node.get("parts", []) or []:
            _walk(part)

    _walk(payload)
    return by_cid, ordered
