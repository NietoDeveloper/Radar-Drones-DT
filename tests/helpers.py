from __future__ import annotations

import numpy as np

from sdt_radar.config import Settings, SiteConfig
from sdt_radar.geo import LocalFrame, enu_to_polar
from sdt_radar.models import Detection, SensorConfig, SensorKind

T0 = 1_795_000_000.0
SITE = SiteConfig(lat=4.7110, lon=-74.0721, alt_m=2600.0)
FRAME = LocalFrame(SITE.lat, SITE.lon, SITE.alt_m)
