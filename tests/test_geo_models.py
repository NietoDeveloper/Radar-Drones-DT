import math

import numpy as np
import pytest
from pydantic import ValidationError

from sdt_radar.geo import LocalFrame, enu_to_polar, heading_deg, polar_covariance, polar_to_enu
from sdt_radar.models import Detection, SensorConfig, Zone, decode_iq, encode_iq
from tests.helpers i