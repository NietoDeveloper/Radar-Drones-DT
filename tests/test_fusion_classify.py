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


def test_classifier_save_load_roundtrip_and_feature_guard(clf, tmp_path):
    p = tmp_path / "m.npz"
    clf.save(p)