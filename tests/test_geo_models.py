import math

import numpy as np
import pytest
from pydantic import ValidationError

from sdt_radar.geo import LocalFrame, enu_to_polar, heading_deg, polar_covariance, polar_to_enu
from sdt_radar.models import Detection, SensorConfig, Zone, decode_iq, encode_iq
from tests.helpers import T0


def test_enu_roundtrip_and_earth_curvature():
    f = LocalFrame(4.711, -74.0721, 2600.0)
    enu = f.to_enu(4.72, -74.06, 2700.0)
    assert 1300 < enu[0] < 1400 and 950 < enu[1] < 1050
    assert e

def test_polar_conventions_azimuth_clockwise_from_north():
    assert polar_to_enu(100, 0, 0) == pytest.approx([0, 100, 0], abs=1e-9)  # north
    assert polar_to_enu, 90, 0) == pytest.approx([100, 0, 0], abs=1e-9)  # east
    assert polar_to_enu(100, 0, 90) == pytest.approx([0, 0, 100], abs=1e-9)  # up
    r, az, el = enu_to_polar(polar_to_enu(500, 217.0, 12.0))
    assert (r, az, el) == pytest.approx((500, 217.0, 12.0))
    assert heading_deg(0, 1) == 0 and heading_deg(1, 0) == 90 and heading_deg(0, -1) == 180


def test_polar_covariance_is_symmetric_psd_and_anisotropic():
    c = polar_covariance(2000, 30, 5, 3, 1.0, 2.0)
    assert np.allclose(c, c.T)
    assert np.all(np.linalg.eigvalsh(c) > 0)
    near, far = polar_covariance(200, 30, 5, 3, 1, 2), polar_covariance(2000, 30, 5, 3, 1, 2)
    assert np.trace(far) > np.trace(near)  # cross-range error grows with range


def _polar(**kw):
    return dict(sensor_id="r1", t=T0, range_m=1000, azimuth_deg=10, elevation_deg=5, **kw)


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
