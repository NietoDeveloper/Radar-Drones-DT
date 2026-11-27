import numpy as np
import pytest

from sdt_radar.classification import MicroDopplerClassifier, load_default_classifier, md_features, synth_bird, synth_multirotor
from sdt_radar.classification.model import make_dataset
from sdt_radar.fusion import MeasurementFactory, RejectedDetection, ReorderBuffer, group_batches
from sdt_radar.models import ClassPosterior, Detection, Measurement, SensorKind, TargetClass, encode_iq
from tests.helpers import FRAME, T0, geodetic_det, polar_det, sensor_cfg


        md_features(np.ones(100, dtype=complex), 10_240.0)
)).sum() / (y == 0).sum()
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
