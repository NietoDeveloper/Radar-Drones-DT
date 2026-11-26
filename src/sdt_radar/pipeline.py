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
        with self._lock:
            self.factory.add_sensor(sensor)

    def ingest_raw(self, obj: Any) -> bool:
        """Validate an untrusted dict / JSON string / bytes and ingest it."""
        try:
            det = Detection.model_validate_json(obj) if isinstance(obj, (str, bytes)) else Detection.model_validate(obj)
        except ValidationError:
            self.stats["rejected_invalid"] += 1
            return False
        return self.ingest(det)

    def ingest(self, det: Detection, rx_wall: float | None = None) -> bool:
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
                track_id=tr.track_id, seq=tr.seq, status=status or tr.status, target_class=cls,
                class_confidence=cc, confidence=tr.confidence(now, cfg.tracker.max_coast_s),
                lat=float(lat[i]), lon=float(lon[i]), alt_m=float(alt[i]),
                east_m=float(pos[i, 0]), north_m=float(pos[i, 1]), up_m=float(pos[i, 2]),
                vel_e_mps=ve, vel_n_mps=vn, vel_u_mps=vu, speed_mps=float(np.linalg.norm(tr.vel)),
                heading_deg=heading_deg(ve, vn), climb_mps=vu, rcs_dbsm=tr.rcs_dbsm,
                position_sigma_m=tr.position_sigma, sensors=tr.sensor_list(), first_seen=tr.first_t,
                last_seen=tr.last_hit_t, age_s=max(now - tr.first_t, 0.0), hits=tr.hits))
        return out

    # ------------------------------------------------------------------------------- queries
    def snapshot(self, now: float | None = None, include_tentative: bool = False,
                 extrapolate: bool = True) -> list[TrackOut]:
        now = time.time() if now is None else now
        with self._lock:
            tracks = [t for t in self.tracker.active_tracks()
                      if include_tentative or t.status != TrackStatus.tentative]
            return self._track_outs(tracks, now, extrapolate)

    def live_track(self, track_id: str, now: float | None = None) -> TrackOut | None:
        now = time.time() if now is None else now
        with self._lock:
            tr = self.tracker.tracks.get(track_id)
            return self._track_out(tr, now, True) if tr else None

    def live_history(self, track_id: str) -> list[TrackPoint] | None:
        with self._lock:
            tr = self.tracker.tracks.get(track_id)
            if tr is None:
                return None
            hs = list(tr.history)
        if not hs:
            return []
        lat, lon, alt = self.frame.to_geodetic(np.stack([h.x[:3] for h in hs]))
        pts = []
        for i, h in enumerate(hs):
            ve, vn, vu = (float(v) for v in h.x[3:])
            pts.append(TrackPoint(t=h.t, lat=float(lat[i]), lon=float(lon[i]), alt_m=float(alt[i]), vel_e_mps=ve,
                                  vel_n_mps=vn, vel_u_mps=vu, speed_mps=float(np.linalg.norm(h.x[3:])),
                                  heading_deg=heading_deg(ve, vn), position_sigma_m=h.pos_sigma,
                                  confidence=h.confidence, sensors=list(h.sensors)))
        return pts

    def add_zone(self, zone: Zone) -> None:
        with self._lock:
            self.alerts.add_zone(zone)
        self.store.put_zone(zone)

    def remove_zone(self, zone_id: str) -> bool:
        with self._lock:
            ok = self.alerts.remove_zone(zone_id)
        if ok:
            self.store.delete_zone(zone_id)
        return ok

    def metrics(self) -> dict[str, Any]:
        def pct(d: deque[float], q: float) -> float | None:
            return float(np.percentile(list(d), q)) if d else None

        with self._lock:
            by_status: dict[str, int] = defaultdict(int)
            for t in self.tracker.tracks.values():
                by_status[t.status.value] += 1
            return {
                "counters": dict(self.stats), "tracker": dict(self.tracker.stats), "tracks_by_status": dict(by_status),
                "buffer_len": len(self.buffer), "buffer_dropped": self.buffer.dropped_overflow,
                "latency_ms": {"p50": pct(self.latency_ms, 50), "p95": pct(self.latency_ms, 95),
                               "p99": pct(self.latency_ms, 99)},
                "step_ms": {"p50": pct(self.step_ms, 50), "p99": pct(self.step_ms, 99)},
                "sensors": {k: dict(v) for k, v in self.sensor_state.items()},
                "classifier": None if self.classifier is None else self.classifier.version,
            }
