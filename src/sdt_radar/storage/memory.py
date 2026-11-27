"""In-memory store: same behaviour as the SQL store, no persistence. For tests and demos."""

from __future__ import annotations

import threading

from ..models import AlertOut, TargetClass, TrackOut, TrackPoint, TrackStatus, Zone


class MemoryStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tracks: dict[str, TrackOut] = {}
        self._points: dict[str, list[TrackPoint]] = {}
        self._alerts: dict[str, AlertOut] = {}
        self._zones: dict[str, Zone] = {}

    def start(self) -> None
    def close(self) -> None: ...
    def flush(self, timeout: float = 5.0) -> None: ...

    def write_track(self, track: TrackOut) -> None:
        with self._lock:
    def write_alert(self, alert: AlertOut) -> None:
        with self._lock:
            self._alerts[alert.alert_id] = alert

    def put_zone(self, zone: Zone) -> None:
        with self._lock:
            self._zones[zone.id] = zone

    def delete_zone(self, zone_id: str) -> None:
        with self._lock:
            self._zones.pop(zone_id, None)

    def get_track(self, track_id: str) -> TrackOut | None:
        with self._lock:
            return self._tracks.get(track_id)

    def list_tracks(self, status: TrackStatus | None = None, target_class: TargetClass | None = None,
                    since: float | None = None, limit: int = 1000) -> list[TrackOut]:
        with self._lock:
            rows = [t for t in self._tracks.values()
                    if (status is None or t.status == status)
                    and (target_class is None or t.target_class == target_class)
                    and (since is None or t.last_seen >= since)]
        rows.sort(key=lambda t: t.last_seen, reverse=True)
        return rows[:limit]

    def history(self, track_id: str, since: float | None = None, until: float | None = None,
                limit: int = 5000) -> list[TrackPoint]:
        with self._lock:
            pts = [p for p in self._points.get(track_id, [])
                   if (since is None or p.t >= since) and (until is None or p.t <= until)]
        return pts[:limit]

    def list_alerts(self, active_only: bool = False, since: float | None = None, limit: int = 1000) -> list[AlertOut]:
        with self._lock:
            rows = [a for a in self._alerts.values()
                    if (not active_only or a.state == "open") and (since is None or a.updated_at >= since)]
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
