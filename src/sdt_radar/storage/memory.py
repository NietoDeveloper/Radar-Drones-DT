"""In-memory store: same behaviour as the SQL store, no persistence. For tests and demos."""

from __future__ import annotations

import threading

from ..models import AlertOut, TargetClass, TrackOut, TrackPoint, TrackStatus, Zone


class MemoryStore:
    def __init__(self) -> None:s():
                keep = [p for p in pts if p.t >= older_than]
                n += len(pts) - len(keep)
                self._points[tid] = keep
        return n
