"""Multi-target, multi-sensor tracker.

Algorithm (global-nearest-neighbour, GNN):

1. All tracks are predicted (vectorised) to the reference time of the incoming measurement batch.
2. Coarse Euclidean gating prunes candidate pairs; surviving pairs get an exact Mahalanobis^2
   using the track's innovation covariance plus the *measurement's own* covariance (so a noisy
   Remote ID fix and a sharp radar plot are weighted correctly).
3. Hungarian assignment (scirop(tr, ev)
                continues) if t.status == TrackStatus.tentative],
        )k(tracks[ti_], batch[mj], ev)
        return [batch[j] for j in range(m) if j not in used_m]
s.R.cfg.history_min_dt_s:
            returne)
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
