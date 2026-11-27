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

