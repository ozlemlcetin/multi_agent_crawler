"""Bounded in-memory frontier queue."""

from __future__ import annotations

import queue
from dataclasses import dataclass

from .models import FrontierItem

# Occupancy fraction above which backpressure is signalled to callers.
_BACKPRESSURE_THRESHOLD = 0.80


@dataclass(frozen=True)
class FrontierSnapshot:
    size: int
    capacity: int
    backpressure: bool

    @property
    def occupancy(self) -> float:
        return self.size / self.capacity if self.capacity else 0.0


class Frontier:
    def __init__(self, maxsize: int = 10_000) -> None:
        self._q: queue.Queue[FrontierItem] = queue.Queue(maxsize=maxsize)
        self._capacity = maxsize

    # ------------------------------------------------------------------
    # Write side
    # ------------------------------------------------------------------

    def admit(self, item: FrontierItem) -> bool:
        """Enqueue item if space is available. Returns True on success."""
        try:
            self._q.put_nowait(item)
            return True
        except queue.Full:
            return False

    # ------------------------------------------------------------------
    # Read side (used by future worker threads)
    # ------------------------------------------------------------------

    def get(self, timeout: float = 1.0) -> FrontierItem | None:
        """Dequeue the next item, or return None on timeout."""
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def task_done(self) -> None:
        self._q.task_done()

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def snapshot(self) -> FrontierSnapshot:
        size = self._q.qsize()
        return FrontierSnapshot(
            size=size,
            capacity=self._capacity,
            backpressure=(size / self._capacity) >= _BACKPRESSURE_THRESHOLD,
        )
