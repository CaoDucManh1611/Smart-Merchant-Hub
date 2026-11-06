"""Short-lived, tenant-scoped cache for derived image observations.

Only model output is cached.  Raw customer images and live catalog facts such
as price or stock are never stored here.  The process-local backend is a safe
latency optimization; deployments with several workers may miss the cache but
must produce the same answer.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from hashlib import sha256
from threading import RLock
import time


_entries: OrderedDict[str, tuple[float, dict]] = OrderedDict()
_lock = RLock()


def image_cache_key(*, business_id: int, image_bytes: bytes, model_version: str,
                    analysis_kind: str) -> str:
    if type(business_id) is not int or business_id <= 0 or not image_bytes:
        raise ValueError("invalid image cache scope")
    material = "\0".join((str(business_id), analysis_kind, model_version)).encode("utf-8")
    return sha256(material + b"\0" + sha256(image_bytes).digest()).hexdigest()


def get_image_observation(key: str, *, now: float | None = None) -> dict | None:
    moment = time.monotonic() if now is None else now
    with _lock:
        entry = _entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if moment >= expires_at:
            _entries.pop(key, None)
            return None
        _entries.move_to_end(key)
        return deepcopy(value)


def put_image_observation(key: str, value: dict, *, ttl_seconds: int,
                          max_entries: int, now: float | None = None) -> None:
    if not isinstance(value, dict) or ttl_seconds <= 0 or max_entries <= 0:
        raise ValueError("invalid image cache value or limits")
    moment = time.monotonic() if now is None else now
    with _lock:
        for stale_key, (expires_at, _) in list(_entries.items()):
            if moment >= expires_at:
                _entries.pop(stale_key, None)
        _entries[key] = (moment + ttl_seconds, deepcopy(value))
        _entries.move_to_end(key)
        while len(_entries) > max_entries:
            _entries.popitem(last=False)


def clear_image_observation_cache() -> None:
    with _lock:
        _entries.clear()
