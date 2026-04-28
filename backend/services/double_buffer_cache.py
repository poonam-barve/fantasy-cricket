from __future__ import annotations

import copy
import threading
from typing import Generic, TypeVar

from backend.services.cache_locks import acquire_cache_locks

T = TypeVar("T")


class DoubleBufferCache(Generic[T]):
    """Small live/update cache with atomic publish semantics."""

    def __init__(self, initial: T | None = None, lock_name: str | None = None):
        self._lock = threading.Lock()
        self._live: T | None = copy.deepcopy(initial)
        self._update: T | None = copy.deepcopy(initial)
        self._lock_name = lock_name or f"double_buffer:{id(self)}"

    def read(self) -> T | None:
        with self._lock:
            return copy.deepcopy(self._live)

    def has_live(self) -> bool:
        with self._lock:
            return self._live is not None

    def publish(self, payload: T) -> T:
        """Write to the update slot, then atomically swap it into live."""
        with acquire_cache_locks(self._lock_name):
            with self._lock:
                self._update = copy.deepcopy(payload)
                self._live, self._update = self._update, self._live
                return copy.deepcopy(self._live)

    def invalidate(self) -> None:
        with acquire_cache_locks(self._lock_name):
            with self._lock:
                self._live = None
                self._update = None
