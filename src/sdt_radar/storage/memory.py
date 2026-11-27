"""In-memory store: same behaviour as the SQL store, no persistence. For tests and demos."""

from __future__ import annotations

import threading

from ..models import AlertOut, TargetClass, TrackOut, TrackPoint, TrackStatus, Zone


class MemoryStore:
    def __init__(self) -> None:
        self._lock 
            self._alerts[alert.alert_id] = alert

            self._zones.pop(zone_id, None)

    def get_track(self, track_id: str) -> TrackOut | None:
        with self._lock:
            return self._tracks.get(tract.last_seen >= since)]
        rows.sort(key=lambda t: t.last_seen, reverse=True)
        return rows[:limit]

    def history(self, track_id: str, sis.get(track_id, [])
                   if (since is None or p.t >= since) and (until is None or p.t <= until)]
        return pts[:limit]

    def list_     if (not active_only or a.state == "open") and (since is None or a.updated_at >= since)]
        rows.sort(key=lambda a: a.updated_at, reverse=True)
        return rows[:limit]

    def list_zones(self) -> list[Zone]:
        with self._lock:
            return list(self._zones.values())

    def prune(self, older_than: float) -> int:
        n = 0
        with self._lock:
            for tid, pts in self._points.items():
                keep = [p for p in pts if p.t >= older_than]
                n += len(pts) - len(keep)
                self._points[tid] = keep
        return n
