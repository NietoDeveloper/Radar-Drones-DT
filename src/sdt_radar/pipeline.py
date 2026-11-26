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
                res.lost += len(ev.lost)
                for tr in ev.lost:
                    res.alerts.extend(self.alerts.close_for_track(tr.track_id, now))
                    if tr.announced:
                        self.store.write_track(self._track_out(tr, now, False, TrackStatus.lost))
            self._persist(touched.values(), now)
            if now - self._last_alert_eval >= 0.5 or flush:
                self._last_alert_eval = now
                res.alerts.extend(self.alerts.evaluate(self.tracker.active_tracks(), now))
            for a in res.alerts:
                self.store.write_alert(a)
                for fn in self._alert_listeners:
                    fn(a)
        self.step_ms.append((time.perf_counter() - t0) * 1000.0)
        return res

    # ----------------------------------------------------------------------------- internals
    def _classify(self, tr: Track, ms: Measurement) -> None:
        if self.classifier is None or ms.md_iq is None or ms.md_prf_hz is None:
            return
        try:
            probs = self.classifier.predict_proba(ms.md_iq, ms.md_prf_hz)
        except ValueError:
            self.stats["classifier_rejected"] += 1
            return
        tr.klass.update(probs, self.settings.classifier.forgetting)
        self.stats["classified"] += 1

    def _persist(self, tracks: Iterable[Track], now: float) -> None:
        interval = self.settings.storage.point_interval_s
        for tr in tracks:
            if not tr.announced or tr.t - tr.stored_t < interval:
                continue
            tr.stored_t = tr.t
            out = self._track_out(tr, now, False)
            self.store.write_track(out)
            self.store.write_points(tr.track_id, [TrackPoint(
                t=tr.t, lat=out.lat, lon=out.lon, alt_m=out.alt_m, vel_e_mps=out.vel_e_mps, vel_n_mps=out.vel_n_mps,
                vel_u_mps=out.vel_u_mps, speed_mps=out.speed_mps, heading_deg=out.heading_deg,
                position_sigma_m=out.position_sigma_m, confidence=out.confidence, sensors=out.sensors)])

    def _track_out(self, tr: Track, now: float, extrapolate: bool, status: TrackStatus | None = None) -> TrackOut:
        return self._track_outs([tr], now, extrapolate, status)[0]

    def _track_outs(self, tracks: list[Track], now: float, extrapolate: bool = True,
                    status: TrackStatus | None = None) -> list[TrackOut]:
        if not tracks:
            return []
        cfg = self.settings
        pos = np.stack([
            t.pos + t.vel * float(np.clip(now - t.t, 0.0, cfg.tracker.max_coast_s)) if extrapolate else t.pos
            for t in tracks])
        lat, lon, alt = self.frame.to_geodetic(pos)
        out: list[TrackOut] = []
        for i, tr in enumerate(tracks):
            cls, cc = tr.klass.decide(cfg.classifier.decision_threshold)
            ve, vn, vu = (float(v) for v in tr.vel)
            out.append(TrackOut(
                track_id=tr.track_id, seq=tr.seq, staacks()
                      if include_tentative or t.status != TrackStatus.tentative]
            return self._track_outs(tracks, now, extrapolate)

    def live_track(self, track_id: str, now: float | None = None) -> TrackOut | None:
        now = time.time() if now is None else now
        with self._lock:
            tr = self.tracker.tracks.get(track_id)
            return self._track_out(tr, now, True) if tr else None

    def live_history(self, track_id: str) -> list[TrackPoint] | None:
        with self._loc