from __future__ import annotations

import numpy as np

from sdt_radar.config import Settings, SiteConfig
from sdt_radar.geo import LocalFrame, enu_to_polar
from sdt_radar.models import Detection, SensorConfig, SensorKind

T0 = 1_795_000_000.0
SITE = SiteConfig(lat=4.7110, lon=-74.0721, alt_m=2600.0)
FRAME = LocalFrame(SITE.lat, SITE.lon, SITE.alt_m)


def sensor_cfg(sid: str = "r1", kind: SensorKind = SensorKind.radar_fmcw, east: float = 0.0, north: float = 0.0,
               alt: float = 5.0, **kw: float) -> SensorConfig:
    lat, lon, a = FRAME.to_geodetic(np.array([east, north, alt]))
    return SensorConfig(id=sid, kind=kind, lat=float(lat), lon=float(lon), alt_m=float(a), **kw)  # type: ignore[arg-type]


def settings_for(*sensors: SensorConfig, **kw: object) -> Settings:
    data: dict = {"site": SITE, "sensors": list(sensors), "storage": {"kind": "memory"}}
    data.update(kw)
    return Settings.model_vaat, sensor.lon, sensor.alt_m)
    r, az, el = enu_to_polar(target_enu - s_enu)
    if noise is not None:
        r, Detection(sensor_id=sensor_id, t=t, lat=float(lat), lon=float(lon), alt_m=float(alt), **extra)  # type: ignore[arg-type]
