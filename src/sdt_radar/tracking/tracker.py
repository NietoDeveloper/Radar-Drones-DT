"""Multi-target, multi-sensor tracker.

Algorithm (global-nearest-neighbour, GNN, with an IMM motion model):

1. All tracks are predicted (vectorised IMM mix + predict) to the reference time of the incoming batch.
2. Coarse Euclidean gating prunes candidate pairs; surviving pairs get an exact Mahalanobis^2
   using the track's innovation covariance plus the *measurement's own* covariance (so a noisy
   Remote ID fix and a sharp radar plot are weighted correctly).
3. Hungarian assignment (scipy) on the gated cost matrix, confirmed/coasting tracks first, then
   tentative tracks on what is left.
4. Each matched track is propagated to *its* measurement's timestamp and updated per model (Joseph form);
   radar plots also contribute a Doppler (range-rate) update when the sensor reports radial velocity.
5. Unmatched position measurements spawn tentative tracks; lifecycle (confirm / coast / delete / merge)
   is swept by time, so it works for rotating radars, staring AESAs and 1 Hz Remote ID alike.
6. Bearing-only sensors (EO/IR, acoustic / RF direction finders) are gated in angle space and refine
   existing tracks through an extended Kalman update; they cannot start a track (no range).

Measurements older than a track's state are discarded and counted (the reorder buffer in
``fusion`` makes this rare).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

from ..config import TrackerConfig
from ..models import Measurement, TrackStatus
from . import kalman
from .imm import Imm, Linearise
from .meas import ang_lin, dop_lin, pos_lin
from .track import HistoryPoint, Track

_BIG = 1e9


@dataclass(slots=True)
class TrackerEvents:
    """What changed during one ``process`` / ``sweep`` call."""

    created: list[Track] = field(default_factory=list)
    confirmed: list[Track] = field(default_factory=list)
    updated: list[tuple[Track, Measurement]] = field(default_factory=list)
    lost: list[Track] = field(default_factory=list)
    merged: list[tuple[Track, Track]] = field(default_factory=list)  # (dropped, kept)
    stale_measurements: int = 0


class MultiTargetTracker:
    def __init__(self, cfg: TrackerConfig | None = None) -> None:
        self.cfg = cfg or TrackerConfig()
        self.tracks: dict[str, Track] = {}
        self._seq = 0
        self.imm = (Imm(self.cfg.imm_sigma_h_mps2, self.cfg.imm_sigma_v_mps2, self.cfg.imm_stay_prob)
                    if self.cfg.imm_enabled
                    else Imm((self.cfg.sigma_accel_h_mps2,), (self.cfg.sigma_accel_v_mps2,)))
        self.stats = {"created": 0, "confirmed": 0, "lost": 0, "merged": 0, "stale": 0, "dropped_capacity": 0,
                      "angular_updates": 0, "angular_unmatched": 0, "doppler_updates": 0}

    # ------------------------------------------------------------------------------- public API
    def active_tracks(self) -> list[Track]:
        return list(self.tracks.values())

    def process(self, batch: Sequence[Measurement], now: float | None = None) -> TrackerEvents:
        """Associate and fuse a batch of measurements (any mix of sensors), then sweep lifecycle."""
        ev = TrackerEvents()
        if len({(m.sensor_id, m.geom) for m in batch}) > 1:  # one association pass per sensor and geometry
            groups: dict[tuple[str, str], list[Measurement]] = {}
            for m in batch:
                groups.setdefault((m.sensor_id, m.geom), []).append(m)
            for g in sorted(groups.values(), key=lambda g: min(m.t for m in g)):
                sub = self.process(g, now)
                ev.created += sub.created
                ev.confirmed += sub.confirmed
                ev.updated += sub.updated
                ev.lost += sub.lost
                ev.merged += sub.merged
                ev.stale_measurements += sub.stale_measurements
            return ev
        if batch:
            t_ref = float(np.mean([m.t for m in batch]))
            if batch[0].geom == "ang":
                self._update_angular(list(batch), t_ref, ev)
            else:
                for m in self._associate_and_update(list(batch), t_ref, ev):
                    self._spawn(m, ev)
            now = max(now if now is not None else t_ref, t_ref)
        elif now is None:
            return ev
        self.sweep(now, ev)
        return ev

    def sweep(self, now: float, ev: TrackerEvents | None = None) -> TrackerEvents:
        """Time-based lifecycle: confirm, coast, delete, merge duplicates."""
        ev = ev or TrackerEvents()
        cfg = self.cfg
        for tr in list(self.tracks.values()):
            silent = now - tr.last_hit_t
            if tr.status == TrackStatus.tentative:
                if silent > cfg.tentative_timeout_s:
                    self._drop(tr, ev)
                continue
            if silent > cfg.max_coast_s or float(np.linalg.norm(tr.x[3:])) > cfg.max_track_speed_mps:
                self._drop(tr, ev)  # lost, or kinematically impossible (a ghost fed by neighbouring plots)
            elif silent > cfg.coast_after_s:
                tr.status = TrackStatus.coasting
        self._merge_duplicates(ev)
        return ev

    # ------------------------------------------------------------------------------ internals
    def _associate_and_update(self, batch: list[Measurement], t_ref: float, ev: TrackerEvents) -> list[Measurement]:
        cfg = self.cfg
        tracks = list(self.tracks.values())
        if not tracks:
            return batch
        n, m = len(tracks), len(batch)

        xp, pp = self._predict_all(tracks, t_ref)[:2]

        z = np.stack([mm.z for mm in batch])  # (m,3)
        r = np.stack([mm.R for mm in batch])  # (m,3,3)

        # coarse gate on Euclidean distance (cheap), then exact Mahalanobis on candidates only
        diff = z[None, :, :] - xp[:, None, :3]  # (n,m,3)
        dist = np.linalg.norm(diff, axis=2)
        sig_t = np.sqrt(np.trace(pp[:, :3, :3], axis1=1, axis2=2) / 3.0)
        sig_m = np.sqrt(np.trace(r, axis1=1, axis2=2) / 3.0)
        radius = 5.0 * (sig_t[:, None] + sig_m[None, :]) + 5.0
        ti, mi = np.nonzero(dist < radius)

        cost = np.full((n, m), _BIG)
        if ti.size:
            s = pp[ti, :3, :3] + r[mi]
            y = diff[ti, mi]  # (k,3)
            sol = np.linalg.solve(s, y[:, :, None])[:, :, 0]
            d2 = np.einsum("ki,ki->k", y, sol)
            ok = d2 < cfg.gate_chi2
            cost[ti[ok], mi[ok]] = d2[ok]

        matched_pairs: list[tuple[int, int]] = []
        used_m: set[int] = set()
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

    def _predict_all(self, tracks: list[Track], t_ref: float) -> tuple[np.ndarray, np.ndarray]:
        """Fused predicted state/covariance of every track at ``t_ref`` (vectorised IMM)."""
        imm = self.imm
        for t in tracks:
            t.ensure_models(imm.m, imm.mu0)
        xs = np.stack([t.xs for t in tracks])
        ps = np.stack([t.Ps for t in tracks])
        mu = np.stack([t.mu for t in tracks])
        dt = np.array([max(t_ref - t.t, 0.0) for t in tracks])
        xp, pp, c = imm.predict(xs, ps, mu, dt)
        return Imm.combine(c, xp, pp)

    def _update_angular(self, batch: list[Measurement], t_ref: float, ev: TrackerEvents) -> None:
        """Gate bearing-only measurements in angle space (Hungarian) and refine matched tracks."""
        # Bearing-only data refines tracks that radar/position sensors have *currently* established. It never
        # feeds tentative tracks (a line of sight crosses many clutter points: false confirmations) nor
        # coasting ones (it cannot fix range, so it would keep a ghost alive on a wrong point of the ray).
        tracks = [t for t in self.tracks.values() if t.status == TrackStatus.confirmed]
        if not tracks:
            self.stats["angular_unmatched"] += len(batch)
            return
        xp, pp = self._predict_all(tracks, t_ref)
        rel = xp[:, :3] - batch[0].sensor_pos
        e, n, u = rel[:, 0], rel[:, 1], rel[:, 2]
        rh2 = np.maximum(e * e + n * n, 1.0)
        rh = np.sqrt(rh2)
        r2 = rh2 + u * u
        az, el = np.arctan2(e, n), np.arctan2(u, rh)
        hn = np.zeros((len(tracks), 2, 3))
        hn[:, 0, 0], hn[:, 0, 1] = n / rh2, -e / rh2
        hn[:, 1, 0], hn[:, 1, 1], hn[:, 1, 2] = -u * e / (r2 * rh), -u * n / (r2 * rh), rh / r2
        a = np.einsum("nij,njk,nlk->nil", hn, pp[:, :3, :3], hn)  # (N,2,2) predicted angular covariance
        z = np.stack([m.z for m in batch])  # (M,2)
        r = np.stack([m.R for m in batch])  # (M,2,2)
        y0 = (z[None, :, 0] - az[:, None] + np.pi) % (2 * np.pi) - np.pi  # wrapped azimuth innovation (N,M)
        y1 = z[None, :, 1] - el[:, None]
        s = a[:, None] + r[None]  # (N,M,2,2)
        det = s[..., 0, 0] * s[..., 1, 1] - s[..., 0, 1] ** 2
        d2 = (s[..., 1, 1] * y0**2 - 2 * s[..., 0, 1] * y0 * y1 + s[..., 0, 0] * y1**2) / np.maximum(det, 1e-18)
        cost = np.where(d2 < self.cfg.angle_gate_chi2, d2, _BIG)
        used: set[int] = set()
        if np.any(cost < _BIG):
            ri, ci = linear_sum_assignment(cost)
            for a_, b_ in zip(ri, ci, strict=True):
                if cost[a_, b_] < _BIG:
                    self._update_track(tracks[a_], batch[b_], ev)
                    used.add(int(b_))
        self.stats["angular_unmatched"] += len(batch) - len(used)

    def _update_track(self, tr: Track, ms: Measurement, ev: TrackerEvents) -> None:
        cfg = self.cfg
        dt = ms.t - tr.t
        if dt < 0.0:  # measurement older than the filter state: cannot rewind
            ev.stale_measurements += 1
            self.stats["stale"] += 1
            return
        imm = self.imm
        tr.ensure_models(imm.m, imm.mu0)
        assert tr.xs is not None and tr.Ps is not None and tr.mu is not None
        xp, pp, c = imm.predict(tr.xs[None], tr.Ps[None], tr.mu[None], np.array([dt]))
        meas: list[tuple[Linearise, Measurement, float | None]] = [
            (pos_lin if ms.geom == "pos" else ang_lin, ms, None)]
        if (ms.geom == "pos" and cfg.use_doppler and ms.sigma_rv is not None
                and ms.radial_velocity is not None and ms.sensor_pos is not None):
            meas.append((dop_lin, ms, cfg.doppler_gate_chi2))
            self.stats["doppler_updates"] += 1
        if ms.geom == "ang":
            self.stats["angular_updates"] += 1
        tr.xs, tr.Ps, tr.mu = imm.update(xp[0], pp[0], c[0], meas)
        x, p = Imm.combine(tr.mu[None], tr.xs[None], tr.Ps[None])
        tr.x, tr.P = x[0], p[0]
        tr.t = ms.t
        tr.sensors[ms.sensor_id] = ms.t
        if ms.geom == "ang":  # refinement only: existence evidence (hits / freshness / status) is untouched
            self._record_history(tr, ms.t)
            ev.updated.append((tr, ms))
            return
        tr.last_hit_t = ms.t
        tr.hits += 1
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
        tr.ensure_models(self.imm.m, self.imm.mu0)
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
            # The 6-D chi-square already weighs the velocity difference by both tracks' velocity uncertainty:
            # a poorly-known duplicate (huge velocity variance) merges, two well-known crossing targets do not.
            stat = cfg.merge_chi2 > 0 and float(diff @ np.linalg.solve(pa + pb, diff)) < cfg.merge_chi2
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
