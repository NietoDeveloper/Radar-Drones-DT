import math

import numpy as np
import pytest
from pydantic import ValidationError

from sdt_radar.config import TrackerConfig
from sdt_radar.fusion import MeasurementFactory
from sdt_radar.geo import polar_covariance, polar_to_enu
from sdt_radar.models import Detection, Measurement, SensorKind, TrackStatus
from sdt_radar.tracking import MultiTargetTracker
from sdt_radar.tracking.imm import Imm
from sdt_radar.tracking.meas import ang_lin, dop_lin, pos_lin
from tests.helpers import FRAME, T0, sensor_cfg

SENSOR = np.array([0.0, 0.0, 5.0])


def fd_jacobian(fn, x, eps=1e-5):
    """Numerical Jacobian of the *predicted measurement* (innovation y = z - h(x) => dh = -dy)."""
    base = fn(x)[0]
    cols = []
    for i in range(6):
        d = np.zeros(6)
        d[i] = eps
        cols.append(-(fn(x + d)[0] - base) / eps)
    return np.stack(cols, axis=1)


def ang_meas():
    return Measurement("eo", T0, np.array([math.radians(40.0), math.radians(5.0)]), np.eye(2) * 1e-6,
                       SensorKind.eo_ir, geom="ang", sensor_pos=SENSOR)


def test_angle_and_doppler_jacobians_match_finite_differences():
    x = np.array([800.0, -300.0, 120.0, 12.0, -7.0, 2.0])
    m = ang_meas()
    _, h, _ = ang_lin(x, m)
    assert np.allclose(h, fd_jacobian(lambda s: ang_lin(s, m), x), atol=1e-7)
    dm = Measurement("r", T0, np.zeros(3), np.eye(3), SensorKind.radar_fmcw, radial_velocity=3.0, sensor_pos=SENSOR, sigma_rv=0.5)
    _, hd, rd = dop_lin(x, dm)
    assert np.allclose(hd, fd_jacobian(lambda s: dop_lin(s, dm), x), atol=1e-7) and rd[0, 0] == pytest.approx(0.25)
    y, _, _ = ang_lin(np.array([-1000.0, 1000.0, 0, 0, 0, 0]), Measurement(  # azimuth wrap across 0/360
        "eo", T0, np.array([math.radians(359.0), 0.0]), np.eye(2), SensorKind.eo_ir, geom="ang", sensor_pos=np.zeros(3)))
    assert y[0] == pytest.approx(math.radians(44.0), abs=1e-9)  # 359 vs 315 deg: shortest way round is +44, not -316
    assert pos_lin(x, Measurement("a", T0, x[:3] + 2.0, np.eye(3), SensorKind.rf))[0] == pytest.approx([2, 2, 2])


def test_angular_detections_validate_and_convert_to_radians_with_sensor_position():
    Detection(sensor_id="eo", t=T0, azimuth_deg=40.0, elevation_deg=5.0)
    for bad in ({"azimuth_deg": 40.0}, {"elevation_deg": 5.0}, {"range_m": 100.0, "azimuth_deg": 1.0}):
        with pytest.raises(ValidationError):
            Detection(sensor_id="eo", t=T0, **bad)
    eo = sensor_cfg("eo", SensorKind.eo_ir, east=100, north=50, alt=10, sigma_az_deg=0.2, sigma_el_deg=0.3, north_offset_deg=2.0)
    m = MeasurementFactory(FRAME, [eo]).convert(Detection(sensor_id="eo", t=T0, azimuth_deg=40.0, elevation_deg=5.0))
    assert m.geom == "ang" and m.z == pytest.approx([math.radians(42.0), math.radians(5.0)])
    assert m.R[0, 0] == pytest.approx(math.radians(0.2) ** 2) and m.R[1, 1] == pytest.approx(math.radians(0.3) ** 2)
    assert m.sensor_pos == pytest.approx([100, 50, 10], abs=0.5)
    unknown = MeasurementFactory(FRAME, [])
    with pytest.raises(Exception, match="unregistered"):
        unknown.convert(Detection(sensor_id="eo", t=T0, azimuth_deg=40.0, elevation_deg=5.0))


def radar_meas(truth_pos, truth_vel, t, rng, doppler=True, sigma_rv=0.5):
    rel = truth_pos - SENSOR
    rng_m = float(np.linalg.norm(rel))
    az = math.degrees(math.atan2(rel[0], rel[1])) % 360
    el = math.degrees(math.atan2(rel[2], math.hypot(rel[0], rel[1])))
    r, a, e = rng_m + rng.normal(0, 4), az + rng.normal(0, 0.8), el + rng.normal(0, 1.5)
    z = SENSOR + polar_to_enu(r, a, e)
    vr = float(truth_vel @ rel) / rng_m + rng.normal(0, 0.3)
    return Measurement("r1", t, z, polar_covariance(r, a, e, 4.0, 0.8, 1.5), SensorKind.radar_fmcw,
                       radial_velocity=vr if doppler else None, sensor_pos=SENSOR, sigma_rv=sigma_rv if doppler else None)


def test_doppler_aided_update_sharpens_velocity_estimates():
    def vel_rmse(use_doppler, seed):
        rng = np.random.default_rng(seed)
        tr = MultiTargetTracker(TrackerConfig(use_doppler=use_doppler))
        p0, v = np.array([1500.0, 400.0, 90.0]), np.array([-14.0, 3.0, 0.5])
        errs = []
        for k in range(40):
            tr.process([radar_meas(p0 + v * k, v, T0 + k, rng)])
            if k > 12:
                errs.append(np.linalg.norm(next(iter(tr.tracks.values())).x[3:] - v))
        return float(np.sqrt(np.mean(np.square(errs)))), tr
    without = np.mean([vel_rmse(False, s)[0] for s in range(5)])
    with_d = np.mean([vel_rmse(True, s)[0] for s in range(5)])
    assert with_d < without * 0.8
    assert vel_rmse(True, 0)[1].stats["doppler_updates"] == 39  # first plot only spawns the track


def test_corrupt_doppler_is_gated_not_trusted():
    rng = np.random.default_rng(1)
    tr = MultiTargetTracker()
    p0, v = np.array([1500.0, 400.0, 90.0]), np.array([-14.0, 3.0, 0.5])
    for k in range(30):
        m = radar_meas(p0 + v * k, v, T0 + k, rng)
        if k >= 20:
            m.radial_velocity = (m.radial_velocity or 0.0) + 40.0  # aliased / spoofed range-rate
        tr.process([m])
    est = next(iter(tr.tracks.values())).x[3:]
    assert np.linalg.norm(est - v) < 6.0  # the gate rejected the +40 m/s outliers


def test_bearing_only_sensor_refines_cross_range_but_cannot_start_or_confirm_tracks():
    eo_pos = np.array([600.0, -200.0, 10.0])
    p0, v = np.array([1200.0, 900.0, 80.0]), np.array([-10.0, -6.0, 0.0])
    R_poor = np.diag([40.0**2, 40.0**2, 60.0**2])

    def run(with_eo):
        r2 = np.random.default_rng(7)
        tr = MultiTargetTracker()
        err = []
        for k in range(60):
            truth = p0 + v * k
            batch = [Measurement("gps", T0 + k, truth + r2.normal(0, [40, 40, 60]), R_poor, SensorKind.radar_fmcw)]
            tr.process(batch)
            if with_eo:
                rel = truth - eo_pos
                az = math.atan2(rel[0], rel[1]) + r2.normal(0, math.radians(0.1))
                el = math.atan2(rel[2], math.hypot(rel[0], rel[1])) + r2.normal(0, math.radians(0.1))
                tr.process([Measurement("eo", T0 + k + 0.1, np.array([az, el]), np.eye(2) * math.radians(0.1) ** 2,
                                        SensorKind.eo_ir, geom="ang", sensor_pos=eo_pos)])
            if k > 20:
                err.append(np.linalg.norm(next(iter(tr.tracks.values())).x[:3] - truth))
        assert len(tr.tracks) == 1
        return float(np.sqrt(np.mean(np.square(err)))), tr
    base, _ = run(False)
    fused, tr = run(True)
    assert fused < base * 0.7 and tr.stats["angular_updates"] >= 50
    # a bearing with no track to refine is counted and never creates a track
    empty = MultiTargetTracker()
    empty.process([Measurement("eo", T0, np.array([0.3, 0.1]), np.eye(2) * 1e-6, SensorKind.eo_ir, geom="ang", sensor_pos=eo_pos)])
    assert not empty.tracks and empty.stats["angular_unmatched"] == 1
    # ...and bearings never confirm a tentative (possibly false) track
    tent = MultiTargetTracker()
    tent.process([Measurement("r", T0, np.array([500.0, 500.0, 50.0]), np.eye(3) * 25, SensorKind.radar_fmcw)])
    tr0 = next(iter(tent.tracks.values()))
    rel = tr0.x[:3] - eo_pos
    az, el = math.atan2(rel[0], rel[1]), math.atan2(rel[2], math.hypot(rel[0], rel[1]))
    for k in range(6):
        tent.process([Measurement("eo", T0 + 0.1 * k, np.array([az, el]), np.eye(2) * 1e-6, SensorKind.eo_ir,
                                  geom="ang", sensor_pos=eo_pos)])
    assert tr0.status == TrackStatus.tentative and tr0.hits == 1


def test_imm_invariants_no_transition_at_zero_dt_and_probabilities_stay_valid():
    imm = Imm((1.5, 8.0), (1.0, 4.0), 0.95)
    rng = np.random.default_rng(0)
    xs = rng.normal(size=(3, 2, 6))
    a = rng.normal(size=(3, 2, 6, 6))
    ps = np.einsum("nmij,nmkj->nmik", a, a) + np.eye(6)
    mu = np.array([[0.7, 0.3], [0.5, 0.5], [0.99, 0.01]])
    xp, pp, c = imm.predict(xs, ps, mu, np.zeros(3))
    assert np.allclose(xp, xs) and np.allclose(pp, ps) and np.allclose(c, mu)  # dt = 0: nothing happens
    xp, pp, c = imm.predict(xs, ps, mu, np.array([1.0, 2.0, 0.5]))
    assert np.allclose(c.sum(axis=1), 1.0) and np.all(c > 0)
    assert np.all(np.linalg.eigvalsh(pp) > 0)
    x, p = Imm.combine(c, xp, pp)
    assert x.shape == (3, 6) and np.allclose(p, p.transpose(0, 2, 1))
    one = Imm((4.0,), (2.5,))
    assert one.m == 1 and np.allclose(one.mu0, [1.0])
    # switching probability is per second: two 0.5 s steps equal one 1 s step
    m1 = imm.predict(xs[:1], ps[:1], mu[:1], np.array([1.0]))[2]
    half = imm.predict(xs[:1], ps[:1], mu[:1], np.array([0.5]))
    two = imm.predict(half[0], half[1], half[2], np.array([0.5]))[2]
    assert np.allclose(m1, two, atol=0.02)


def test_imm_follows_a_manoeuvre_better_than_a_quiet_single_model():
    def run(cfg, seed):
        rng = np.random.default_rng(seed)
        tr = MultiTargetTracker(cfg)
        pos, vel = np.array([1000.0, 0, 80]), np.array([0.0, 18.0, 0])
        err = []
        for k in range(60):
            if 25 <= k < 35:  # coordinated turn: 9 m/s^2 lateral acceleration for 10 s
                w = 9.0 / 18.0
                vel = np.array([vel[0] * math.cos(w) + vel[1] * math.sin(w), -vel[0] * math.sin(w) + vel[1] * math.cos(w), 0.0])
            pos = pos + vel
            tr.process([Measurement("r", T0 + k, pos + rng.normal(0, 5, 3), np.eye(3) * 25, SensorKind.radar_fmcw)])
            if 25 <= k < 45:
                err.append(np.linalg.norm(next(iter(tr.tracks.values())).x[:3] - pos))
        return float(np.sqrt(np.mean(np.square(err)))), len(tr.tracks), tr.stats["created"]

    quiet = TrackerConfig(imm_enabled=False, sigma_accel_h_mps2=1.5, sigma_accel_v_mps2=1.0)
    imm = TrackerConfig()
    rq = [run(quiet, s) for s in range(4)]
    ri = [run(imm, s) for s in range(4)]
    assert np.mean([r[0] for r in ri]) < np.mean([r[0] for r in rq])
    assert all(r[2] == 1 for r in ri)  # the IMM never lost the target (no second track born)
