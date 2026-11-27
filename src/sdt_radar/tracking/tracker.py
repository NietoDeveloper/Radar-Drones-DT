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
            keep.sensors.update({k: max(v, keep.sen
            ev.merged.append((drop, keep))
