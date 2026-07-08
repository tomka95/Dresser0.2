"""Run-scoped fetched-once cache (P3.7 split of the image_resolver god-module).

Keeps "resolve each source exactly once" isolated from the waterfall/tier
logic in resolve.py -- this concern only knows about locking + a sentinel for
a failed/refused source, nothing about tiers, HTML, or storage.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, Dict, Optional, Tuple

from app.gmail_closet.image_guard import GuardRejection

logger = logging.getLogger(__name__)

_FAILED = object()  # sentinel: this key was tried and refused/errored — do not retry


class ResolvedImageCache:
    """Thread-safe "resolve each source exactly once" cache for a single run.

    Keyed by the resolved source (remote URL, or ``cid:<msg>:<id>`` for inline). The
    value is the stored Supabase URL on success, None when storage is unavailable, or
    the _FAILED sentinel when the fetch/upload was refused. Per-key locking means two
    items (or two worker threads) that resolve to the SAME url fetch + upload it once.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: Dict[str, object] = {}
        self._keylocks: Dict[str, threading.Lock] = {}

    def _keylock(self, key: str) -> threading.Lock:
        with self._lock:
            kl = self._keylocks.get(key)
            if kl is None:
                kl = threading.Lock()
                self._keylocks[key] = kl
            return kl

    def get_or_create(self, key: str, producer: Callable[[], Optional[str]]) -> Tuple[object, bool]:
        """Return (value, hit). On miss, run ``producer`` once under the key's lock.

        ``producer`` returns the stored URL (or None if storage is unavailable). A
        GuardRejection (or any error) is swallowed and cached as _FAILED so the same
        bad source is never retried within the run.
        """
        with self._lock:
            if key in self._values:
                return self._values[key], True

        with self._keylock(key):
            with self._lock:
                if key in self._values:
                    return self._values[key], True
            try:
                value: object = producer()
            except GuardRejection as exc:
                logger.info("image resolve refused: reason=%s host=%s", exc.reason, exc.host)
                value = _FAILED
            except Exception as exc:  # storage/upload/parse errors — never fatal
                logger.warning("image resolve error: %s", type(exc).__name__)
                value = _FAILED
            with self._lock:
                self._values[key] = value
            return value, False
