import numpy as np
import pytest

from sdt_radar.classification import MicroDopplerClassifier, load_default_classifier, md_features, synth_bird, synth_multirotor
from sdt_radar.classification.model import make_dataset
from sdt_radar.fusion import MeasurementFactory, RejectedDetection, ReorderBuffer, group_batches
from sdt_radar.models import ClassPosterior, Detection, Measurement, SensorKind, TargetClass, encode_iq
from tests.helpers import FRAME, T0, geodetic_det, polar_det, sensor_cfg


def test_measurement_conversion_polar_matches_geometry_and_north_offset():
    s = sensor_cfg("r1", east=500.0, north=-200.0
def test_reorder_buffer_sorts_holds_and_sheds_oldest():
    def mk(t, sid="r1"):
        return Measurement(sid, T0 + t, np.zeros(3), np.eye(3), SensorKind.radar_fmcw)

    b = ReorderBuffer(wind == 1
    assert [m.t - T0 for m in b.flush()] == [3.0, 4.0, 5.0, 6.0]  # the oldest (2.0) was shed, order preserved
    batches = group_baault_classifier()


def test_features_are_finite_fixed_length_and_reject_short_snippets(rng):
    f = md_features(synth_multirotor(rng, 1024, 10_240.0), 10_240.0)
    assert f.shape == (7,) and np.all(np.isfinite(f))
    with pytest.raises(ValueError):
        md_features(np.ones(100, dtype=complex), 10_240.0)


def test_drone_and_bird_signatures_differ_in_the_expected_direction(rng):
    drone = np.mean([md_features(synth_multirotor(rng, 1024, 10_240.0, snr_db=20), 10_240.0) for _ in range(20)], axis=0)
    bird = np.mean([md_features(synth_bird(rng, 1024, 10_240.0, snr_db=20), 10_240.0) for _ in range(20)], axis=0)
    assert drone[0] > bird[0] * 2  # rotor micro-Doppler is much wider than wing-beat micro-Doppler
    assert drone[3] > bird[3]  # rotors are stationary in time; wing flaps are not


def test_classifier_heldout_accuracy_on_synthetic_data(clf):
    x, y = make_dataset(120, seed=424242)
    pred = clf.predict_proba_features(x).argmax(axis=1)
    assert (pred == y).mean() > 0.88
    drone_as_bird = ((y == 0) & (pred == 1)).sum() / (y == 0).sum()
    bird_as_drone = ((y == 1) & (pred == 0)).sum() / (y == 1).sum()
    assert drone_as_bird < 0.05 and bird_as_drone < 0.05  # the confusion that matters operationally


def test_track_level_evidence_accumulates_to_a_confident_decision(clf, rng):
    post = ClassPosterior()
    assert post.decide(0.7) == (TargetClass.unknown, 0.0)
    for _ in range(6):
        post.update(clf.predict_proba(synth_bird(rng, 1024, 10_240.0, snr_db=10), 10_240.0), 0.92)
    cls, conf = post.decide(0.7)
    assert cls == TargetClass.bird and conf > 0.9


def test_classifier_save_load_roundtrip_and_feature_guard(clf, tmp_path):
    p = tmp_path / "m.npz"
    clf.save(p)
    again = MicroDopplerClassifier.load(p)
    f = md_features(synth_multirotor(np.random.default_rng(0), 1024, 10_240.0), 10_240.0)
    assert np.allclose(clf.predict_proba_features(f), again.predict_proba_features(f))
    assert encode_iq(np.zeros(4, dtype=np.complex64))  # payload helper still works
