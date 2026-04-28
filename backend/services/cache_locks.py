from __future__ import annotations

import threading
from contextlib import contextmanager

_LOCK_REGISTRY: dict[str, threading.RLock] = {}
_LOCK_REGISTRY_LOCK = threading.Lock()


def get_cache_lock(name: str) -> threading.RLock:
    normalized = str(name).strip()
    if not normalized:
        raise ValueError("Cache lock name must not be empty")

    with _LOCK_REGISTRY_LOCK:
        lock = _LOCK_REGISTRY.get(normalized)
        if lock is None:
            lock = threading.RLock()
            _LOCK_REGISTRY[normalized] = lock
        return lock


@contextmanager
def acquire_cache_locks(*names: str):
    ordered_names = []
    for name in names:
        normalized = str(name).strip()
        if normalized and normalized not in ordered_names:
            ordered_names.append(normalized)

    ordered_names.sort()
    locks = [get_cache_lock(name) for name in ordered_names]

    for lock in locks:
        lock.acquire()
    try:
        yield
    finally:
        for lock in reversed(locks):
            lock.release()


# Backward-compatible alias used only in places that still expect a single lock.
CACHE_WRITE_LOCK = get_cache_lock("legacy_write")

# Legacy alias for older refresh flows. New code should prefer acquire_cache_locks().
CACHE_REFRESH_LOCK = get_cache_lock("legacy_refresh")
