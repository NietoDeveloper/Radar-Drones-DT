"""Detection (sensor frame) -> Measurement (shared ENU frame + covariance).

This is where multi-sensor fusion starts: radars (polar, range-dependent anisotropic noise) and
geodetic sources (Remote ID, RF geolocation, EO/IR fixes) are all expressed as ENU position +
covariance, so the tracker needs no sensor-specific code.
"""

from __future__ import annotations

import math

import numpy as np

from ..geo import LocalFrame, polar_covariance, polar_to_enu
from ..models import Detection, Measurement, SensorConfig, SensorKind, decode_iq

_DEFAULT_SIGMA_H = 10.0
_VERT_FACTOR = 1.5


class RejectedDetection(ValueError):
    """Detection is well-formed but cannot be used (unknown sensor, unusable payload)."""


class MeasurementFactory:
    def __init__(self, frame: LocalFrame, sensors: list[SensorConfig], allow_unknown: bool = False) -> None:
        self.frame = frame
        self.allow_unknown = allow_unknown
        self.sensors: dict[str, SensorConfig] = {}
        self._sensor_enu: dict[str, np.ndarray] = {}
        for s in sensors:
            self.add_sensor(s)

    def add_sensor(self, s: SensorConfig) -> None:
        self.sensors[s.id] = s
        self._sensor_enu[s.id] = self.frame.to_enu(s.lat, s.lon, s.alt_m)

    def convert(self, det: Detection, rx_wall: float = 0.0) -> Measurement:
        sensor = self.sensors.get(det.sensor_id)
        md = None
        if det.md_iq_b64 is not None:
            try:
                md = decode_iq(det.md_iq_b64)
            except ValueError as exc:
                raise RejectedDetection(str(exc)) from exc

        geom: str = "pos"
        sensor_pos = None
        sigma_rv = None
        if det.geometry == "polar":
            if sensor is None:
                raise RejectedDetection(f"polar detection from unregistered sensor '{det.sensor_id}'")
            assert det.range_m is not None and det.azimuth_deg is not None and det.elevation_deg is not None
            az = det.azimuth_deg + sensor.north_offset_deg
            sensor_pos = self._sensor_enu[sensor.id]
            z = sensor_pos + polar_to_enu(det.range_m, az, det.elevation_deg)
            r = polar_covariance(det.range_m, az, det.elevation_deg, sensor.sigma_range_m,
                                 sensor.sigma_az_deg, sensor.sigma_el_deg)
            kind = sensor.kind
            if det.radial_velocity_mps is not None:
                sigma_rv = sensor.sigma_radial_velocity_mps
        elif det.geometry == "angular":
            if sensor is None:
                raise RejectedDetection(f"angular detection from unregistered sensor '{det.sensor_id}'")
            assert det.azimuth_deg is not None and det.elevation_deg is not None
            geom, sensor_pos, kind = "ang", self._sensor_enu[sensor.id], sensor.kind
            z = np.array([math.radians((det.azimuth_deg + sensor.north_offset_deg) % 360.0),
                          math.radians(det.elevation_deg)])
            r = np.diag([math.radians(sensor.sigma_az_deg) ** 2, math.radians(sensor.sigma_el_deg) ** 2])
        else:
            if sensor is None and not self.allow_unknown:
                raise RejectedDetection(f"detection from unregistered sensor '{det.sensor_id}'")
            assert det.lat is not None and det.lon is not None and det.alt_m is not None
            z = self.frame.to_enu(det.lat, det.lon, det.alt_m)
            sh = det.sigma_h_m or (sensor.sigma_range_m if sensor else _DEFAULT_SIGMA_H)
            sv = det.sigma_v_m or sh * _VERT_FACTOR
            r = np.diag([sh * sh, sh * sh, sv * sv])
            kind = sensor.kind if sensor else SensorKind.other

        return Measurement(
            sensor_id=det.sensor_id, t=det.t, z=np.asarray(z, dtype=float), R=np.asarray(r, dtype=float),
            kind=kind, radial_velocity=det.radial_velocity_mps, rcs_dbsm=det.rcs_dbsm, snr_db=det.snr_db,
            external_id=det.external_id, md_iq=md, md_prf_hz=det.md_prf_hz, rx_wall=rx_wall,
            geom=geom, sensor_pos=sensor_pos, sigma_rv=sigma_rv,  # type: ignore[arg-type]
        )
