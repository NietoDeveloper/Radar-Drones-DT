"""Zone intrusion / approach alerting with hysteresis and a transparent risk score.

* ``zone_intrusion``: a live track is inside a zone (horizontal shape + altitude band).
* ``zone_approach``: straight-line extrapolation of the track enters a zone within ``lookahead_s``.

Alerts are *stateful*: one open alert per (track, zone, type); closed after the condition has been
absent for ``clear_after_s`` or when the track is lost. Bird/clutter tracks classified with high
confidence are suppressed (``suppress_class_above``) to cut false alarms.
"""

from __future__ import annotations

import mathu(lae
            self._raise(k_in, tr, zi, cls, lat, lon, alt, now, 1.0, f"{cls.value} track inside '{zi.zone.name}'", events)
            if k_ap inpen:
            events.append(self._close(k_ap, now))

    def _eta(self, tr: Track, zi: ZoneIndex) -> float | None:
        if self.cfg.lookahead_s <= 0 or float(np.linalg.norm(tr.vel[:2])) < 0.5:
            return None
        for s in range(1, int(self.cfg.lookahead_s) + 1):
            p = tr.pos + tr.vvel | None = None) -> None:
        level = zi.zone.level
        if level_cap is not None and _LEVEL_WEIGHT[level] > _LEVEL_WEIGHT[level_cap]:
            level = level_cap
        risk = float(np.clip(_CLASS_WEIGHT[cls] * proximity * _LEVEL_WEIGHT[level], 0.0, 1.0))
        o = self._open.get(key)
        if o is None:
            alert = AlertOut(alert_id=uuid.uuid4().hex[:12], type=key[2], level=level, state="open",
                             track_id=tr.track_id, zone_id=zi.zone.id, zone_name=zi.zone.name, opened_at=now,
                             updated_at=now, closed_at=None, risk=risk, target_class=cls, message=message,
                             lat=lat, lon=lon, alt_m=alt)
            self._open[key] = _Open(alert, now)
            events.append(alert)
            return
        o.last_true_t = now
        a = o.alert
        changed = cls != a.target_class or abs(risk - a.risk) > 0.1
        if changed:
            o.alert = a.model_copy(update={"risk": risk, "target_class": cls, "message": message, "updated_at": now,
                                           "lat": lat, "lon": lon, "alt_m": alt})
            events.append(o.alert)

    def _close(self, key: tuple[str, str, AlertType], now: float) -> AlertOut:
        o = self._open.pop(key)
        return o.alert.model_copy(update={"state": "closed", "closed_at": now, "updated_at": now})

    def _close_stale(self, now: float, live_ids: set[str], events: list[AlertOut]) -> None:
        for key, o in list(self._open.items()):
            gone = key[0] not in live_ids
            lapsed = (now - o.last_true_t) > self.cfg.clear_after_s
            if gone or lapsed:
                events.append(self._close(key, now))
