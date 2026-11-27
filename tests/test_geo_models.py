import math

import numpy as np
import pytest
from pydantic import ValidationError

from sdt_radar.geo import LocalFrame, enu_to_polar, heading_deg, polar_covariance, polar_to_enu
from sdt_radar.models import Detection, SensorConfig, Zone, decode_iq, encode_iq
from tests.helpers import T0



def test_polar_conventions_azs
    assert np.all(np.linalg.eigvalsh(c) > 0)
    near, far = polar_covariance(200, 30, 5, 3, 1, 2)muth_deg=10, elevation_deg=5, **kw)


def test_detection_requires_exactly_one_geometry():
    Detection(**_polar())
    Detection(sensor_id="rid", t=T0, lat=4.7, lon=-74.0, alt_m=2700)
    with pytest.raises(ValidationError):
        Detection(sensor_id="x", t=T0)  # none
    with pytest.raises(ValidationError):
        Detection(sensor_id="x", t=T0, range_m=1, azimuth_deg=1)  # partial polar
    with pytest.raises(ValidationError):
        Detection(**_polar(), lat=1, lon=1, alt_m=1)  # both


@pytest.mark.parametrize("bad", [
    {"t": 12.0}, {"t": float("nan")}, {"range_m": -5.0}, {"elevation_deg": 120.0}, {"rcs_dbsm": 1e3},
    {"unknown_field": 1}, {"sensor_id": ""},
])
def test_detection_rejects_bad_values(bad):
    with pytest.raises(ValidationError):
        Detection(**{**_polar(), **bad})


def test_micro_doppler_payload_roundtrip_and_validation():
    iq = (np.random.default_rng(0).normal(size=300) + 1j * np.random.default_rng(1).normal(size=300)).astype(np.complex64)
    assert np.allclose(decode_iq(encode_iq(iq)), iq)
    with pytest.raises(ValidationError):
        Detection(**_polar(), md_iq_b64=encode_iq(iq))  # prf missing
    with pytest.raises(ValueError):
        decode_iq("AAAA")  # not whole complex64 samples
    nan_iq = np.array([complex(float("nan"), 0)], dtype=np.complex64)
    with pytest.raises(ValueError):
        decode_iq(encode_iq(nan_iq))


def test_zone_and_sensor_validation():
    Zone(id="a", name="A", kind="circle", center_lat=4.7, center_lon=-74.0, radius_m=100)
    with pytest.raises(ValidationError):
        Zone(id="a", name="A", kind="circle", center_lat=4.7)
    with pytest.raises(ValidationError):
        Zone(id="p", name="P", kind="polygon", polygon=[(1, 1), (2, 2)])
    with pytest.raises(ValidationError):
        Zone(id="a", name="A", kind="circle", center_lat=4.7, center_lon=-74.0, radius_m=100, min_alt_m=50, max_alt_m=10)
    with pytest.raises(ValidationError):
        SensorConfig(id="s", kind="radar_fmcw", lat=95, lon=0)
    assert math.isfinite(SensorConfig(id="s", kind="rf", lat=1, lon=1).sigma_range_m)
