"""Pipeline orchestrator: detections in -> tracks, classes, alerts, records and events out.

The pipeline is **synchronous and deterministic**: time is an explicit argument (``step(now)``), so the
same code serves live operation (``now = time.time()``), replay and simulation (``now = data time``)
and tests. Network, API and WebSocket layers wrap it; none of them contain tracking logic.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

    # ----------------------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._started:
sd