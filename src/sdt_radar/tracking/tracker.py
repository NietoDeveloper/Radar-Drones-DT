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
s.R.cfg.history_min_dt_s:< b.seq else (b, a)
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
