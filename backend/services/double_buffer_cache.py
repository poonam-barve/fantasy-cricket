from __future__ import annotations

import copy
import threading
from typing import Generic, TypeVar

T = TypeVar("T")


class DoubleBufferCache(Generic[T]):
    """Small live/update cache with atomic publish semantics."""

    def __init__(self, initial: T | None = None):
        self._lock = threading.Lock()
        self._live: T | None = copy.deepcopy(initial)
        self._update: T | None = copy.deepcopy(initial)

    def read(self) -> T | None:
        with self._lock:
            return copy.deepcopy(self._live)

    def has_live(self) -> bool:
        with self._lock:
            return self._live is not None

    def publish(self, payload: T) -> T:
        """Write to the update slot, then atomically swap it into live."""
        with self._lock:
            self._update = copy.deepcopy(payload)
            self._live, self._update = self._update, self._live
            return copy.deepcopy(self._live)

    def invalidate(self) -> None:
        with self._lock:
            self._live = None
            self._update = None

