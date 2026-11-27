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
    data: dict = {"site": SITE, "sensors": list(sensors), "storage": {"kind": "memory"}, "audit": {"enabled": False}}
    data.update(kw)
    return Settings.model_validate(data)


def polar_det(sensor: SensorConfig, target_enu: np.ndarray, t: float, noise: np.ndarray | None = None,
              **extra: object) -> Detection:
    s_enu = FRAME.to_enu(sensor.lat, sensor.lon, sensor.alt_m)
    r, az, el = enu_to_polar(target_enu - s_enu)
    if noise is not None:
        r, az, el = r + noise[0], (az + noise[1]) % 360.0, float(np.clip(el + noise[2], -89, 89))
    return Detection(sensor_id=sensor.id, t=t, range_m=max(r, 0.0), azimuth_deg=az, elevation_deg=el, **extra)  # type: ignore[arg-type]


def geodetic_det(sensor_id: str, target_enu: np.ndarray, t: float, **extra: object) -> Detection:
    lat, lon, alt = FRAME.to_geodetic(target_enu)
    return Detection(sensor_id=sensor_id, t=t, lat=float(lat), lon=float(lon), alt_m=float(alt), **extra)  # type: ignore[arg-type]
