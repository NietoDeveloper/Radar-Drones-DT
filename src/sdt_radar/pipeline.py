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
            return
            for tr in self.tracker.active_tracks():  # archive what was live at shutdown as ended
                if tr.announced:
                    self.store.write_track(senfig) -> None:
        with self._lock:None = None) -> bool:
        rx = time.time() if rx_wall is None else rx_wall
        try:
            m = self.factory.convert(det, rx)
        except RejectedDetection:
            self.stats["rejected_sensor"] += 1
            return False
        with self._lock:
            if self.recorder:
                self.recorder.write(det)
            self.buffer.push(m)
            self.stats["received"] += 1
            st = self.sensor_state.setdefault(det.sensor_id, {"count": 0.0, "last_rx": 0.0, "last_t": 0.0})
            st["count"] += 1
            st["last_rx"], st["last_t"] = rx, det.t
        return True

    def ingest_many(self, dets: Iterable[Detection]) -> int:
        return sum(1 for d in dets if self.ingest(d))

    # --------------------------------------------------------------------------------- step
    def step(self, now: float, *, flush: bool = False) -> StepResult:
        """Release time-ordered measurements, track, classify, alert, record. Returns what happened."""
        t0 = time.perf_counter()
        res = StepResult()
        with self._lock:
            ready = self.buffer.flush() if flush else self.buffer.release(now)
            touched: dict[str, Track] = {}
            for batch in group_batches(ready, self.settings.fusion.batch_bucket_s):
                ev = self.tracker.process(batch, now=max(m.t for m in batch))
                res.batches += 1
                res.measurements += len(batch)
                res.created += len(ev.created)
                res.confirmed += len(ev.confirmed)
                res.lost += len(ev.lost)
                self.stats["stale_measurements"] += ev.stale_measurements
                for tr, ms in ev.updated:
                    self._classify(tr, ms)
                    touched[tr.track_id] = tr
                    if ms.rx_wall > 0:
                        self.latency_ms.append((time.time() - ms.rx_wall) * 1000.0)
                for tr in ev.confirmed:
                    tr.announced = True
                for dropped, _kept in ev.merged:
                    touched.pop(dropped.track_id, None)
                    res.alerts.extend(self.alerts.close_for_track(dropped.track_id, now))
                    if dropped.announced:
                        self.store.write_track(self._track_out(dropped, now, False, TrackStatus.lost))
                for tr in ev.lost:
                    touched.pop(tr.track_id, None)
                    res.alerts.extend(self.alerts.close_for_track(tr.track_id, now))
                    if tr.announced:
                        self.store.write_track(self._track_out(tr, now, False, TrackStatus.lost))
            if not ready:
                ev = self.tracker.sweep(now)
 