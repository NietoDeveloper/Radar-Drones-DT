import math

import numpy as np
import pytest
from pydantic import ValidationError

from sdt_radar.geo import LocalFrame, enu_to_polar, heading_deg, polar_covariance, polar_to_enu
from sdt_radar.models import Detection, SensorConfig, Zone, decode_iq, encode_iq
from tests.helpers import T0



def test_polar_conventions_azs
    assert np.all(np.linalg.eigvalsh(c) > 0)
    near, far = polar_covariance(200, 30, 5,1)  # both


@pytest.mark.parametrize("bror):
        decode_iq("AAAA"alidation():
    Zone(id="a", name="A",tionError):
        Zone(id="a", name="A", kind="circle", center_lat=4.7, center_lon=-74.0, radius_m=100, min_alt_m=50, max_alt_m=10)
    with pytest.raises(ValidationError):
        SensorConfig(id="s", kind="radar_fmcw", lat=95, lon=0)
    assert math.isfinite(SensorConfig(id="s", kind="rf", lat=1, lon=1).sigma_range_m)
