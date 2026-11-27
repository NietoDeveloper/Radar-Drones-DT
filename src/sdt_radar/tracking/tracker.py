"""Multi-target, multi-sensor tracker.

Algorithm (global-nearest-neighbour, GNN):

1. All tracks are predicted (vectorised) to the reference time of the incoming measurement batch.
2. Coarse Euclidean gating prunes candidate pairs; surviving pairs get an exact Mahalanobis^2
   using the track's innovation covariance plus the *measurement's own* covariance (so a noisy
   Remote ID fix and a sharp radar plot are weighted correctly).
3. Hungarian assignment (scirop(tr, ev)
                continue
            if silent > cfg.max_coast_s:
                self._drop(tr, ev)
            elif silent > cfg.coast_after_s:
                tack([t.x for t in tracks])
        p = np.stack([t.P for t in tracks])
        dt = np.array([max(t_ref - t.t, 0.0) for t in tracks])
        xp, pp = kalman.batch_predict(x, p, dt, cfg.sigma_accel_h_mps2, cfg.sigma_accel_v_mps2)

        z = np.stack([mm.z for mm in batch])  # (m,3)
        r = np.stack([mm.R for mm in batch])  # (m,3,3)
(dist < radius)

        cost = np.full((n, m), _BIG)
        if ti.size:
            s = pp[ti, :3, :3] + r[mi]
            y = diff[ = set()
        stage_sets = (
            [i for i, t in enumerate(tracks) if t.status != TrackStatus.tentative],
            [i for i, t in enumerate(tracks) if t.status == TrackStatus.tentative],
        )
        for rows in stage_sets:
            cols = [j for j in range(m) if j not in used_m]
            if not rows or not cols:
                continue
            sub = cost[np.ix_(rows, cols)]
            if not np.any(sub < _BIG):
                continue
            ri, ci = linear_sum_assignment(sub)
            for a, b in zip(ri, ci, strict=True):
                if sub[a, b] < _BIG:
                    matched_pairs.append((rows[a], cols[b]))
                    used_m.add(cols[b])

        for ti_, mj in matched_pairs:
            self._update_track(tracks[ti_], batch[mj], ev)
        return [batch[j] for j in range(m) if j not in used_m]

    def _update_track(self, tr: Track, ms: Measurement, ev: TrackerEvents) -> None:
        cfg = self.cfg
        dt = ms.t - tr.t
        if dt < 0.0:  # measurement older than the filter state: cannot rewind
            ev.stale_measurements += 1
            self.stats["stale"] += 1
            return
        if dt > 0.0:
            tr.x, tr.P = kalman.predict(tr.x, tr.P, dt, cfg.sigma_accel_h_mps2, cfg.sigma_accel_v_mps2)
        tr.x, tr.P, _ = kalman.update(tr.x, tr.P, ms.z, ms.R)
        tr.t = ms.t
        tr.last_hit_t = ms.t
        tr.hits += 1
        tr.sensors[ms.sensor_id] = ms.t
        if ms.external_id:
            tr.external_ids.add(ms.external_id)
        if ms.rcs_dbsm is not None:
            tr.rcs_dbsm = ms.rcs_dbsm if tr.rcs_dbsm is None else 0.8 * tr.rcs_dbsm + 0.2 * ms.rcs_dbsm
        if tr.status == TrackStatus.coasting:
            tr.status = TrackStatus.confirmed
        if (tr.status == TrackStatus.tentative and tr.hits >= cfg.confirm_hits
                and (ms.t - tr.first_t) <= cfg.confirm_window_s
                and float(np.linalg.norm(tr.x[3:])) <= cfg.max_confirm_speed_mps):
            tr.status = TrackStatus.confirmed
            self.stats["confirmed"] += 1
            ev.confirmed.append(tr)
        self._record_history(tr, ms.t)
        ev.updated.append((tr, ms))

    def _spawn(self, ms: Measurement, ev: TrackerEvents) -> None:
        cfg = self.cfg
        if len(self.tracks) >= cfg.max_tracks:
            self.stats["dropped_capacity"] += 1
            return
        self._seq += 1
        x = np.zeros(6)
        x[:3] = ms.z
        p = np.zeros((6, 6))
        p[:3, :3] = ms.R
        p[3:, 3:] = np.eye(3) * cfg.init_velocity_sigma_mps**2
        tr = Track(seq=self._seq, x=x, P=p, t=ms.t, first_t=ms.t, last_hit_t=ms.t)
        tr.sensors[ms.sensor_id] = ms.t
        if ms.external_id:
            tr.external_ids.add(ms.external_id)
        tr.rcs_dbsm = ms.rcs_dbsm
        self.tracks[tr.track_id] = tr
        self.stats["created"] += 1
        self._record_history(tr, ms.t)
        ev.created.append(tr)
        ev.updated.append((tr, ms))

    def _record_history(self, tr: Track, t: float) -> None:
        if t - tr.last_hist_t < self.cfg.history_min_dt_s:
            return
        tr.last_hist_t = t
        tr.history.append(
            HistoryPoint(t, tr.x.copy(), tr.position_sigma, tr.confidence(t, self.cfg.max_coast_s), tuple(tr.sensor_list()))
        )
        while len(tr.history) > self.cfg.history_len:
            tr.history.popleft()

    def _drop(self, tr: Track, ev: TrackerEvents) -> None:
        tr.status = TrackStatus.lost
        self.tracks.pop(tr.track_id, None)
        self.stats["lost"] += 1
        ev.lost.append(tr)

    def _merge_duplicates(self, ev: TrackerEvents) -> None:
        """Merge confirmed/coasting tracks that are statistically the same target.

        Two tracks are merged if their 6-D state difference is consistent with zero given their
        combined covariances (chi-square gate), or if they are within ``merge_distance_m`` with a similar
        velocity. The older track survives and inherits sensors, identifiers and class evidence.
        """
        cfg = self.cfg
        live = [t for t in self.tracks.values() if t.status != TrackStatus.tentative]
        if len(live) < 2 or (cfg.merge_distance_m <= 0 and cfg.merge_chi2 <= 0):
            return
        pos = np.stack([t.x[:3] for t in live])
        close = np.argwhere(np.triu(np.linalg.norm(pos[:, None] - pos[None], axis=2) < 250.0, k=1))
        gone: set[str] = set()
        for i, j in close:
            a, b = live[i], live[j]
            if a.track_id in gone or b.track_id in gone:
                continue
            dt = b.t - a.t  # align the older state to the newer one before comparing
            xa, pa = (a.x, a.P) if dt <= 0 else kalman.predict(a.x, a.P, dt, cfg.sigma_accel_h_mps2, cfg.sigma_accel_v_mps2)
            xb, pb = (b.x, b.P) if dt >= 0 else kalman.predict(b.x, b.P, -dt, cfg.sigma_accel_h_mps2, cfg.sigma_accel_v_mps2)
            diff = xa - xb
            dvel = float(np.linalg.norm(diff[3:]))
            dpos = float(np.linalg.norm(diff[:3]))
            stat = cfg.merge_chi2 > 0 and float(diff @ np.linalg.solve(pa + pb, diff)) < cfg.merge_chi2 \
                and dvel <= 2.0 * cfg.merge_speed_diff_mps
            simple = cfg.merge_distance_m > 0 and dpos < cfg.merge_distance_m and dvel <= cfg.merge_speed_diff_mps
            if not (stat or simple):
                continue
            keep, drop = (a, b) if a.seq < b.seq else (b, a)
            keep.sensors.update({k: max(v, keep.sensors.get(k, 0.0)) for k, v in drop.sensors.items()})
            keep.external_ids |= drop.external_ids
            keep.hits = max(keep.hits, drop.hits)
            keep.last_hit_t = max(keep.last_hit_t, drop.last_hit_t)
            if keep.status == TrackStatus.coasting and drop.status == TrackStatus.confirmed:
                keep.status = TrackStatus.confirmed
            if drop.klass.n > keep.klass.n:
                keep.klass = drop.klass
            self.tracks.pop(drop.track_id, None)
            gone.add(drop.track_id)
            self.stats["merged"] += 1
            ev.merged.append((drop, keep))
