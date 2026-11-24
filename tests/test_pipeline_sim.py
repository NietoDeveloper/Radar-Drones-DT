import json

import numpy as np
import pytest

from sdt_radar.ingest import JsonlRecorder, parse_payload, read_jsonl, replay
from sdt_radar.models import Detection, TargetClass, TrackStatus, encode_iq
from sdt_radar.pipeline import Pipeline
from sdt_radar.radar import RADAR_CATALOG, radar_range_m, range_resolution_m, snr_db_at_range, velocity_resolution_mps
from sdt_radar.sim import generate, perimeter_scenario, run_scenario, swarm_scenario
from tests.helpers import T0, polar_det, sensor_cfg, settings_for


def feed_linear(pipe, sensor, n=8, v=(15.0, 5.0, 0.0), p0=(1500.0, 500.0, 90.0), md=None, noise=0.0):
    rng = np.random.default_rng(0)
    for k in range(n):
        pos = np.array(p0) + np.array(v) * k
        nz = rng.normal(0, [noise, noise * 1e-3, noise * 1e-3]) if noise else None
        extra = {}
        if md is not None:
            extra = {"md_iq_b64": encode_iq(md(k)), "md_prf_hz": 10_240.0}
        pipe.ingest(polar_det(sensor, pos, T0 + k, nz, **extra), rx_wall=0.0)
        pipe.step(T0 + k + 0.5)


def test_pipeline_tracks_a_target_end_to_end_and_reports_geodetic_output():
    s = sensor_cfg("r1")
    pipe = Pipeline(settings_for(s)); pipe.start()
    feed_linear(pipe, s)
    out = pipe.snapshot(T0 + 8.0, extrapolate=False)
    assert len(out) == 1 and out[0].status == TrackStatus.confirmed
    t = out[0]
    assert t.speed_mps == pytest.approx(15.8, abs=1.5) and t.heading_deg == pytest.approx(71.6, abs=5)
    assert t.sensors == ["r1"] and 4.7 < t.lat < 4.8 and -74.1 < t.lon < -74.0 and t.alt_m > 2600
    assert pipe.metrics()["counters"]["received"] == 8


def test_invalid_and_unknown_inputs_are_counted_never_crash():
    s = sensor_cfg("r1")
    pipe = Pipeline(settings_for(s)); pipe.start()
    assert not pipe.ingest_raw({"sensor_id": "r1", "t": T0, "range_m": -1})  # invalid
    assert not pipe.ingest_raw("not json at all")
    assert not pipe.ingest_raw(b"\xff\xfe")
    assert not pipe.ingest(Detection(sensor_id="nope", t=T0, range_m=1, azimuth_deg=0, elevation_deg=0))
    assert pipe.stats["rejected_invalid"] == 3 and pipe.stats["rejected_sensor"] == 1
    assert parse_payload(b'[{"sensor_id":"r1","t":%f,"range_m":10,"azimuth_deg":1,"elevation_deg":1}, 5]' % T0, pipe) == 1
    assert parse_payload(b"{not json}\n{also not}", pipe) == 0 and pipe.stats["rejected_malformed"] == 2
    bad_md = Detection(sensor_id="r1", t=T0, range_m=10, azimuth_deg=1, elevation_deg=1, md_prf_hz=10240.0,
                       md_iq_b64="AAAA")
    assert not pipe.ingest(bad_md)  # undecodable micro-Doppler payload is rejected, not propagated


def test_classification_attaches_and_decides_from_micro_doppler():
    from sdt_radar.classification import synth_multirotor
    s = sensor_cfg("r1")
    pipe = Pipeline(settings_for(s)); pipe.start()
    rng = np.random.default_rng(3)
    feed_linear(pipe, s, n=10, md=lambda k: synth_multirotor(rng, 1024, 10_240.0, snr_db=14))
    t = pipe.snapshot(T0 + 11)[0]
    assert t.target_class == TargetClass.drone and t.class_confidence > 0.9
    assert pipe.stats["classified"] == 10
    short = Detection(sensor_id="r1", t=T0 + 11, range_m=1500, azimuth_deg=70, elevation_deg=3, md_prf_hz=10240.0,
                      md_iq_b64=encode_iq(np.ones(64, dtype=np.complex64)))
    pipe.ingest(short); pipe.step(T0 + 12)
    assert pipe.stats["classifier_rejected"] == 1  # too short to classify: counted, track unaffected


def test_missing_data_makes_tracks_coast_then_disappear_and_get_archived_as_lost():
    s = sensor_cfg("r1")
    pipe = Pipeline(settings_for(s, storage={"kind": "memory", "point_interval_s": 0.5})); pipe.start()
    feed_linear(pipe, s, n=10)
    tid = pipe.snapshot(T0 + 10)[0].track_id
    pipe.step(T0 + 9 + 3.0)
    assert pipe.snapshot(T0 + 12)[0].status == TrackStatus.coasting
    pipe.step(T0 + 9 + 30.0)
    assert pipe.snapshot(T0 + 40) == []
    archived = pipe.store.get_track(tid)
    assert archived is not None and archived.status == TrackStatus.lost
    assert len(pipe.store.history(tid)) >= 5


def test_recorder_and_replay_are_deterministic(tmp_path):
    scn = perimeter_scenario(seed=4, duration_s=40, n_drones=3, n_birds=4)
    dets = generate(scn)
    path = tmp_path / "raw.jsonl"
    rec = JsonlRecorder(path)
    for d in dets:
        rec.write(d)
    rec.close()
    assert sum(1 for _ in open(path)) == len(dets)
    assert next(read_jsonl(path)).sensor_id == dets[0].sensor_id

    def final_state():
        p = Pipeline(scn.settings()); p.start()
        replay(read_jsonl(path), p)
        return sorted((round(t.east_m, 3), round(t.north_m, 3), t.status.value) for t in p.snapshot(dets[-1].t + 0.0, extrapolate=False, include_tentative=True))

    a, b = final_state(), final_state()
    assert a == b and len(a) > 0  # same input -> bit-identical output


def test_pipeline_recorder_setting_logs_what_it_accepts(tmp_path):
    s = sensor_cfg("r1")
    path = tmp_path / "audit.jsonl"
    pipe = Pipeline(settings_for(s, storage={"kind": "memory", "recorder_path": str(path)})); pipe.start()
    pipe.ingest(polar_det(s, np.array([1000.0, 0, 50]), T0)); pipe.ingest_raw({"sensor_id": "r1", "t": 5})
    pipe.close()
    lines = [json.loads(x) for x in open(path)]
    assert len(lines) == 1 and lines[0]["sensor_id"] == "r1"


# ---------------------------------------------------------------- radar equation + simulator
def test_radar_equation_scaling_laws():
    base = dict(peak_power_w=10, gain_dbi=30, freq_hz=10e9, rcs_m2=0.01, min_snr_db=13, bandwidth_hz=10e6)
    r = radar_range_m(**base)
    assert radar_range_m(**{**base, "peak_power_w": 160}) == pytest.approx(2 * r, rel=1e-6)  # R ~ P^(1/4)
    assert radar_range_m(**{**base, "rcs_m2": 0.16}) == pytest.approx(2 * r, rel=1e-6)
    assert snr_db_at_range(r, 10, 30, 10e9, 0.01, 10e6) == pytest.approx(13.0, abs=1e-6)
    assert snr_db_at_range(2 * r, 10, 30, 10e9, 0.01, 10e6) == pytest.approx(13.0 - 12.04, abs=0.01)  # -40 dB/decade
    assert range_resolution_m(150e6) == pytest.approx(1.0, rel=1e-3) and velocity_resolution_mps(10e9, 0.05) == pytest.approx(0.3, rel=1e-2)
    assert {c.key for c in RADAR_CATALOG} >= {"radar_fmcw", "radar_pulse_doppler", "radar_aesa", "radar_passive"}


def test_simulation_is_reproducible_and_detection_probability_falls_with_range():
    a, b = generate(perimeter_scenario(seed=9, duration_s=20)), generate(perimeter_scenario(seed=9, duration_s=20))
    assert len(a) == len(b) and a[0] == b[0] and a[-1] == b[-1]
    assert [d.t for d in a] == sorted(d.t for d in a)
    assert generate(perimeter_scenario(seed=10, duration_s=20)) != a
    from sdt_radar.sim.sensors import RadarModel
    from sdt_radar.sim.targets import Target, Trajectory
    s = sensor_cfg("r", east=0, north=0, alt=0, max_range_m=20000)
    model = RadarModel(s, r90_m=2500, scan_period_s=1.0, fa_per_scan=0.0)
    rng = np.random.default_rng(0)

    def pd_at(r):
        pos = np.array([[0.0, r, 100.0]] * 2)
        tg = Target("t", "drone", -20.0, Trajectory(np.array([0.0, 1e4]), pos, np.zeros((2, 3))))
        return np.mean([bool(model.scan(0.0, T0, [tg], sim_frame(), rng)) for _ in range(400)])

    from tests.helpers import FRAME as sim_frame_  # noqa: N811
    def sim_frame():
        return sim_frame_

    near, at90, far = pd_at(1500), pd_at(2500), pd_at(4500)
    assert near > at90 > far
    assert 0.8 < at90 < 0.97  # r90 definition holds for a 0.01 m^2 target (Swerling I fluctuation)


# ------------------------------------------------------------------------- scenario scoring
def test_perimeter_scenario_meets_the_tracking_requirements():
    scores = []
    for seed in (1, 2, 3):
        pipe, score, alerts = run_scenario(perimeter_scenario(seed=seed))
        scores.append(score)
        assert any(a.type.value == "zone_intrusion" and a.target_class == TargetClass.drone for a in alerts)
        assert not any(a.target_class == TargetClass.bird and a.state == "open" for a in alerts if a.level.value == "critical" and a.risk > 0.5)
    for sc in scores:
        assert sc.detection_rate >= 0.97
        assert sc.false_track_ids <= 3
        assert sc.rmse_horizontal_m < 20.0 and sc.rmse_vertical_m < 25.0
        assert sc.class_coverage > 0.9 and sc.class_accuracy > 0.95
        assert sc.class_drone_vs_bird_wrong <= 2
        assert sc.id_switches <= 12


def test_scale_200_simultaneous_targets_in_realtime_budget():
    scn = swarm_scenario(200, seed=5, duration_s=50)
    pipe, score, _ = run_scenario(scn, step_s=0.5, eval_every_s=2.0, warmup_s=20.0, gate_m=250.0)
    assert score.detection_rate > 0.95
    m = pipe.metrics()
    assert sum(m["tracks_by_status"].values()) >= 190
    busy = [x for x in pipe.step_ms if x > 0.05]
    assert np.percentile(busy, 99) < 500.0  # far below the 2 s scan period and the 500 ms display budget
