"""The u2net matting engine (Collage Phase 1) — local ONNX, CPU, $0 marginal.

DEPLOY SHAPE (the decision, stated once):
  * onnxruntime runs IN-PROCESS on CPU wherever the caller lives — the API
    worker for the birth hook (as a Starlette background task, i.e. after the
    confirm response is sent) and the operator's shell for the backfill script.
    Matting NEVER runs on a request/response hot path and NEVER per collage
    render — it happens once per item, at birth or backfill.
  * the ~176MB u2net.onnx weights are NOT baked into the image. rembg downloads
    them ONCE on first session init into the directory named by the U2NET_HOME
    env var (default ~/.u2net) — point U2NET_HOME at a persistent volume in
    deploy so the download happens once per volume, not once per boot. Local
    dev already has the file (the Phase-0 spike pulled it).
  * session init (graph load) is a one-time ~seconds cost paid lazily on the
    process's FIRST matte — subsequent mattes are ~90-150ms each on CPU. The
    module keeps ONE session for the process lifetime (thread-safe: guarded
    init; onnxruntime sessions are themselves safe for concurrent run()).

Approved decision: u2net ONLY. There is no second-model fallback — a matte the
QA gate refuses marks the item no_matte and the collage renders it flat on its
own tile. (The spike's isnet was equal-or-worse on this closet's hard cases and
a dual-model image costs +180MB.)

The engine is a SEAM: callers go through ``matte_rgba`` on the service module,
which tests monkeypatch — nothing in the suite ever loads the model.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from PIL import Image

from app.core.config import settings

logger = logging.getLogger(__name__)

_session = None
_session_lock = threading.Lock()


def _get_session():
    """The process-wide rembg session, created once (downloads weights on the
    very first use if U2NET_HOME doesn't hold them yet)."""
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                from rembg import new_session  # heavy import deferred to first matte

                _session = new_session(settings.CUTOUT_MODEL)
                logger.info("cutout: matting session ready (model=%s)", settings.CUTOUT_MODEL)
    return _session


def warm() -> bool:
    """Eagerly initialize the session (weights download + graph load) so the
    first real matte doesn't pay it. Optional boot hook; safe to skip. Returns
    False instead of raising when the runtime/model is unavailable."""
    try:
        _get_session()
        return True
    except Exception as exc:
        logger.warning("cutout: warm failed (%s)", type(exc).__name__)
        return False


def matte(img: Image.Image) -> Optional[Image.Image]:
    """One garment matte: product-shot image in, RGBA cutout out (true alpha).
    None when the runtime/model is unavailable or inference fails — callers
    treat that as 'leave the item un-matted for a later backfill', never as an
    error that could block an item's birth."""
    try:
        from rembg import remove

        out = remove(img, session=_get_session())
        return out.convert("RGBA")
    except Exception as exc:
        logger.warning("cutout: matte failed (%s)", type(exc).__name__)
        return None
