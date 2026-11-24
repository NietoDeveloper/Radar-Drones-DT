"""Out-of-order handling: hold measurements for a short, data-time window, then release in order.

Sensors reach the backend over different paths with different latencies. The buffer sorts by
measurement time and releases everything older than ``watermark = now - window``; releases are then
grouped into per-sensor time buckets so the tracker associates one coherent "scan" at a time.
"""

from __future__ import annotations

import heapq
import itertools
from collections import defaultdict

from ..models import Measurement


class ReorderBuffer:
    def __init__(self, window_s: float, max_items: int = 100_000) -> None:
        self.window_s = window_s
        self.max_items = max_items
        self._heap: list[tuple[float, int, Measurement]] = []
        self._counter = itertools.count()
        self.dropped_overflow = 0
        self.max_t_seen = float("-inf")

    def __len__(self) -> int:
        return len(self._heap)

    def push(self, m: Measurement) -> None:
        if len(self._heap) >= self.max_items:  # back-pressure: shed the *oldest* data
            heapq.heappop(self._heap)
            self.dropped_overflow += 1
        heapq.heappush(self._heap, (m.t, next(self._counter), m))
        if m.t > self.max_t_seen:
            self.max_t_seen = m.t

    def release(self, now: float) -> list[Measurement]:
        """Pop every measurement with ``t <= now - window``, in time order."""
        cutoff = now - self.window_s
        out: list[Measurement] = []
        while self._heap and self._heap[0][0] <= cutoff:
            out.append(heapq.heappop(self._heap)[2])
        return out

    def flush(self) -> list[Measurement]:
        out = [heapq.heappop(self._heap)[2] for _ in range(len(self._heap))]
        return out


def group_batches(ms: list[Measurement], bucket_s: float) -> list[list[Measurement]]:
    """Group time-ordered measurements by (sensor, time bucket); batches returned in time order."""
    groups: dict[tuple[str, int], list[Measurement]] = defaultdict(list)
    for m in ms:
        groups[(m.sensor_id, int(m.t // bucket_s))].append(m)
    return sorted(groups.values(), key=lambda g: g[0].t)
