"""Zone intrusion / approach alerting with hysteresis and a transparent risk score.

* ``zone_intrusion``: a live track is inside a zone (horizontal shape + altitude band).
* ``zone_approach``: straight-line extrapolation of the track enters a zone within ``lookahead_s``.

Alerts are *stateful*: one open alert per (track, zone, type); closed after the condition has been
absent for ``clear_after_s`` or when the track is lost. Bird/clutter tracks classified with high
confidence are suppressed (``suppress_class_above``) to cut false alarms.
"""

from __future__ import annotations

import mathu(la, lo, frame.alt_m)[:2] for la,
True)
class _Open:d_zone(
    def list_zones(self) -> list[Zone]:
        return [z.zone for z in self.zones.values()]

    # ----------------------------------------------------------------------------- evaluation
    def evaluate(self, tracks: list[Track], now: float) -> list[AlertOut]:
        """Return alerts that were opened, updated (escalated) or closed during this call."""
        events: list[AlertOut] 
            lat, lon, alt = self.frame.to_geodetic(np.stack([t.pos for t in live]))
        for k, tr in enumerate(live):
            cls, conf = tr.klass.decide(0.5)
            suppressed = cls in (TargetClass.bird, TargetClass.clutter) and conf >= self.cfg.suppress_class_above
            for zi in self.zones.values():
                self._eval_one(tr, zi, cls, float(lat[k]), float(lon[k]), float(alt[k]), now, suppressed, events)
        self._close_stale(now, {t.track_id for t in live}, events)
        return events

    def close_for_track(self, track_id: str, now: float) -> list[AlertOut]:
        out = []
        for key in [k for k in self._open if k[0] == track_id]:
            out.append(self._close(key, now))
        return out

    def open_alerts(self) -> list[AlertOut]:
        return [o.alert for o in self._open.values()]

    # ----------------------------------------------------------------------------- internals
    def _eval_one(self, tr: Track, zi: ZoneIndex, cls: TargetClass, lat: float, lon: float, alt: float,
                  now: float, suppressed: bool, events: list[AlertOut]) -> None:
        inside = zi.contains(tr.pos, alt)
        k_in = (tr.track_id, zi.zone.id, AlertType.zone_intrusion)
        k_ap = (tr.track_id, zi.zone.id, AlertType.zone_approach)
        if suppressed:
            return
        if inside:
            self._raise(k_in, tr, zi, cls, lat, lon, alt, now, 1.0, f"{cls.value} track inside '{zi.zone.name}'", events)
            if k_ap in self._open:
                events.append(self._close(k_ap, now))
            return
        eta = self._eta(tr, zi)
        if eta is not None:
            prox = 0.6 + 0.4 * (1.0 - eta / max(self.cfg.lookahead_s, 1e-9))
            self._raise(k_ap, tr, zi, cls, lat, lon, alt, now, prox,
                        f"{cls.value} track predicted to enter '{zi.zone.name}' in ~{eta:.0f}s", events,
                        level_cap=AlertLevel.warning)
        elif k_ap in self._open:
            events.append(self._close(k_ap, now))

    def _eta(self, tr: Track, zi: ZoneIndex) -> float | None:
        if self.cfg.lookahead_s <= 0 or float(np.linalg.norm(tr.vel[:2])) < 0.5:
            return None
        for s in range(1, int(self.cfg.lookahead_s) + 1):
            p = tr.pos + tr.vel * s
            if zi.contains_xy(float(p[0]), float(p[1])):
                alt_pred = self.frame.alt_m + float(p[2])
                if zi.zone.min_alt_m <= alt_pred <= zi.zone.max_alt_m:
                    return float(s)
        return None

    def _raise(self, key: tuple[str, str, AlertType], tr: Track, zi: ZoneIndex, cls: TargetClass, lat: float,
               lon: float, alt: float, now: float, proximity: float, message: str, events: list[AlertOut],
               level_cap: AlertLevel | None = None) -> None:
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
