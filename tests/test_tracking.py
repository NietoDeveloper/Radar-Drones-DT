import numpy as np
import pytest

from sdt_radar.config import TrackerConfig
from sdt_radar.models import Measurement, SensorKind, TrackStatus
from sdt_radar.tracking import MultiTargetTracker, kalman

R = np.eye(3) * 9.0


def meas(sensor, t, pos, r=R, **kw):
    return Measurement(sensor, t, np.asarray(pos, float), r, SensorKind.radar_fmcw, **kw)


def run_targets(tracker, truth0, vel, n, dt=1.0, noise=3.0, seed=0, sensor="r1", t0=1.7e9):
    rng = np.random.default_rng(seed)
    for k in range(n):
        t = t0 + k * dt
        tracker.process([meas(sensor, t, p + v * k * dt + rng.normal(0, noise, 3)) for p, v in zip(truth0, vel, strict=True)])


def test_kalman_converges_to_velocity_and_stays_consistent():
    rng = np.random.default_rng(3)
    x = np.array([0, 0, 0, 0, 0, 0.0])
    p = np.diag([9, 9, 9, 400, 400, 400.0])
    truth_v = np.array([12.0, -5.0, 1.0])
    d2s = []
    for k in range(1, 60):
        x, p = kalman.predict(x, p, 1.0, 2.0, 1.0)
        z = truth_v * k + rng.normal(0, 3, 3)
        x, p, d2 = kalman.update(x, p, z, R)
        d2s.append(d2)
        assert np.all(np.linalg.eigvalsh(p) > 0) and np.allclose(p, p.T)
    assert x[3:] == pytest.approx(truth_v, abs=1.5)
    assert 0.5 < np.mean(d2s[10:]) < 8.0  # NIS around 3 dof: the filter is not wildly over/under-confident


def test_batch_predict_matches_scalar_predict():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(5, 6))
    a = rng.normal(size=(5, 6, 6))
    p = np.einsum("nij,nkj->nik", a, a) + np.eye(6)
    dt = rng.uniform(0.1, 3, 5)
    xb, pb = kalman.batch_predict(x, p, dt, 4.0, 2.5)
    for i in range(5):
        xs, ps = kalman.predict(x[i], p[i], dt[i], 4.0, 2.5)
        assert np.allclose(xb[i], xs) and np.allclose(pb[i], ps)


def test_tracks_multiple_targets_with_correct_velocities():
    tr = MultiTargetTracker()
    truth0 = [np.array([1000.0, 0, 100]), np.array([-500.0, 800, 60]), np.array([0.0, -1500, 120])]
    vel = [np.array([-15.0, 3, 0]), np.array([8.0, -6, 1]), np.array([0.0, 20, -1])]
    run_targets(tr, truth0, vel, 40)
    assert len(tr.tracks) == 3 and all(t.status == TrackStatus.confirmed for t in tr.tracks.values())
    t_end = 39.0
    for track in tr.tracks.values():
        # match each track to its truth by position, then check velocity within the filter's expected accuracy
        errs = [np.linalg.norm(track.x[:3] - (p + v * t_end)) for p, v in zip(truth0, vel, strict=True)]
        i = int(np.argmin(errs))
        assert errs[i] < 15.0
        assert np.linalg.norm(track.x[3:] - vel[i]) < 5.0
    assert tr.stats["created"] == 3


def test_confirmation_needs_hits_and_clutter_dies():
    cfg = TrackerConfig(confirm_hits=4)
    tr = MultiTargetTracker(cfg)
    rng = np.random.default_rng(5)
    t0 = 1.7e9
    for k in range(30):  # one real target + one random clutter plot per scan
        t = t0 + k
        tr.process([meas("r1", t, [500 + 10 * k, 0, 50]), meas("r1", t, rng.uniform(-2000, 2000, 3))])
    confirmed = [t for t in tr.tracks.values() if t.status == TrackStatus.confirmed]
    assert len(confirmed) == 1
    assert tr.stats["lost"] > 20  # clutter tentatives were deleted


def test_not_confirmed_when_kinematically_implausible():
    tr = MultiTargetTracker(TrackerConfig(max_confirm_speed_mps=50.0))
    for k in range(8):  # 200 m/s
        tr.process([meas("r1", 1.7e9 + k, [200.0 * k, 0, 100])])
    assert all(t.status == TrackStatus.tentative or t.status == TrackStatus.lost for t in tr.tracks.values())


def test_coast_then_delete_by_time_and_reacquire_same_track():
    cfg = TrackerConfig(coast_after_s=2.0, max_coast_s=8.0)
    tr = MultiTargetTracker(cfg)
    run_targets(tr, [np.array([1000.0, 0, 100])], [np.array([-10.0, 0, 0])], 12)
    tid = next(iter(tr.tracks))
    tr.sweep(1.7e9 + 11 + 3.0)
    assert tr.tracks[tid].status == TrackStatus.coasting
    # target reappears where the filter expects it: same track resumes
    t = 1.7e9 + 11 + 4.0
    tr.process([meas("r1", t, [1000 - 10 * 15, 0, 100])])
    assert tr.tracks[tid].status == TrackStatus.confirmed and len(tr.tracks) == 1
    ev = tr.sweep(t + 20.0)
    assert tid not in tr.tracks and ev.lost and ev.lost[0].track_id == tid


def test_stale_measurement_is_counted_not_applied():
    tr = MultiTargetTracker()
    run_targets(tr, [np.array([1000.0, 0, 100])], [np.zeros(3)], 6, noise=0.5)
    track = next(iter(tr.tracks.values()))
    before = track.x.copy()
    ev = tr.process([meas("r1", track.t - 5.0, [1000, 0, 100])])
    assert ev.stale_measurements == 1 and np.allclose(track.x, before)


def test_capacity_limit_is_enforced():
    tr = MultiTargetTracker(TrackerConfig(max_tracks=5))
    tr.process([meas("r1", 1.7e9, [i * 1000.0, 0, 50]) for i in range(20)])
    assert len(tr.tracks) == 5 and tr.stats["dropped_capacity"] == 15


def test_two_sensors_fuse_into_one_track_and_improve_accuracy():
    truth_v = np.array([10.0, 5.0, 0.0])
    p0 = np.array([800.0, 200.0, 80.0])

    def rmse(sensors, seed):
        rng = np.random.default_rng(seed)
        tr = MultiTargetTracker()
        err = []
        for k in range(80):
            t = 1.7e9 + k
            truth = p0 + truth_v * k
            tr.process([meas(s, t, truth + rng.normal(0, 6, 3), np.eye(3) * 36.0) for s in sensors])
            if k > 20:
                err.append(np.linalg.norm(next(iter(tr.tracks.values())).x[:3] - truth))
        assert len(tr.tracks) == 1
        return float(np.sqrt(np.mean(np.square(err))))

    one = np.mean([rmse(["a"], s) for s in range(6)])
    two = np.mean([rmse(["a", "b"], s) for s in range(6)])
    assert two < one * 0.9  # independent sensors reduce the error (ideal: 1/sqrt(2) = 0.71)


def test_duplicate_tracks_on_same_target_are_merged():
    tr = MultiTargetTracker(TrackerConfig(confirm_hits=2))
    t0 = 1.7e9
    for k in range(6):
        tr.process([meas("r1", t0 + k, [20.0 * k, 0, 50])])
    first = next(iter(tr.tracks.values()))
    # force a duplicate seeded slightly offset (as if created by a second sensor)
    from sdt_radar.tracking.track import Track
    dup = Track(seq=99, x=first.x + np.array([4, 3, 0, 0.5, 0, 0]), P=first.P.copy(), t=first.t, first_t=first.t,
                last_hit_t=first.last_hit_t, hits=5, status=TrackStatus.confirmed)
    tr.tracks[dup.track_id] = dup
    ev = tr.sweep(first.t + 0.1)
    assert len(tr.tracks) == 1 and ev.merged and ev.merged[0][1].seq == first.seq
