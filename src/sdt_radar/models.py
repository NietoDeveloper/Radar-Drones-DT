"""Domain and wire models.

Wire/API models are pydantic (strict validation at the edge). Hot-path structures used by the tracker
are plain dataclasses holding numpy arrays.
"""

from __future__ import annotations

import base64
import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ----------------------------------------------------------------------------------------- enums


class SensorKind(StrEnum):
    radar_fmcw = "radar_fmcw"
    radar_pulse_doppler = "radar_pulse_doppler"
    radar_aesa = "radar_aesa"
    radar_passive = "radar_passive"
    rf = "rf"
    remote_id = "remote_id"
    eo_ir = "eo_ir"
    acoustic = "acoustic"
    other = "other"


class TrackStatus(StrEnum):
    tentative = "tentative"
    confirmed = "confirmed"
    coasting = "coasting"
    lost = "lost"


class TargetClass(StrEnum):
    drone = "drone"
    bird = "bird"
    clutter = "clutter"
    unknown = "unknown"


class AlertLevel(StrEnum):
    info = "info"
    warning = "warning"
    critical = "critical"


class AlertType(StrEnum):
    zone_intrusion = "zone_intrusion"
    zone_approach = "zone_approach"


# ------------------------------------------------------------------------------------- sensors


class SensorConfig(BaseModel):
    """Static description of a sensor: where it is and how noisy it is."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    kind: SensorKind
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    alt_m: float = 0.0
    north_offset_deg: float = 0.0  # added to reported azimuth to reference true North
    sigma_range_m: float = Field(5.0, gt=0)
    sigma_az_deg: float = Field(1.0, gt=0)
    sigma_el_deg: float = Field(2.0, gt=0)
    sigma_radial_velocity_mps: float | None = Field(1.5, gt=0, description="range-rate noise; None disables Doppler")
    max_range_m: float | None = Field(None, gt=0)
    scan_period_s: float | None = Field(None, gt=0)
    rate_limit_per_s: float | None = Field(None, gt=0, description="max accepted detections/s from this sensor")
    hmac_secret_env: str | None = Field(None, max_length=128, description="env var holding the sensor's signing secret")
    hmac_secret_file: str | None = Field(None, max_length=512, description="file holding the sensor's signing secret")


# ------------------------------------------------------------------------------- wire detection

MAX_MD_SAMPLES = 16_384


def encode_iq(iq: NDArray[np.complex64] | NDArray[np.complex128]) -> str:
    """Complex slow-time samples -> base64 of interleaved little-endian float32 (I, Q, I, Q, ...)."""
    a = np.asarray(iq, dtype=np.complex64)
    inter = np.empty(a.size * 2, dtype="<f4")
    inter[0::2], inter[1::2] = a.real, a.imag
    return base64.b64encode(inter.tobytes()).decode("ascii")


def decode_iq(b64: str) -> NDArray[np.complex64]:
    raw = base64.b64decode(b64.encode("ascii"), validate=True)
    if len(raw) % 8 != 0:
        raise ValueError("micro-Doppler payload must be a whole number of complex64 samples")
    inter = np.frombuffer(raw, dtype="<f4")
    if not np.all(np.isfinite(inter)):
        raise ValueError("micro-Doppler payload contains non-finite samples")
    out = np.empty(inter.size // 2, dtype=np.complex64)
    out.real, out.imag = inter[0::2], inter[1::2]
    return out


class Detection(BaseModel):
    """One measurement as it arrives from a sensor (UDP / TCP / HTTP / replay).

    Exactly one measurement geometry must be present:

    * polar   -> ``range_m`` + ``azimuth_deg`` + ``elevation_deg`` (relative to the sensor), or
    * geodetic-> ``lat`` + ``lon`` + ``alt_m`` (e.g. Remote ID, RF geolocation, EO/IR triangulation).
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    sensor_id: str = Field(min_length=1, max_length=64)
    t: float  # UNIX epoch seconds (UTC) of the measurement
    range_m: float | None = Field(None, ge=0, le=1_000_000)
    azimuth_deg: float | None = Field(None, ge=-720, le=720)
    elevation_deg: float | None = Field(None, ge=-90, le=90)
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    alt_m: float | None = Field(None, ge=-1000, le=100_000)
    sigma_h_m: float | None = Field(None, gt=0, le=10_000)
    sigma_v_m: float | None = Field(None, gt=0, le=10_000)
    radial_velocity_mps: float | None = Field(None, ge=-1000, le=1000)
    rcs_dbsm: float | None = Field(None, ge=-100, le=100)
    snr_db: float | None = Field(None, ge=-100, le=200)
    external_id: str | None = Field(None, max_length=64)
    md_prf_hz: float | None = Field(None, gt=0, le=1_000_000)
    md_iq_b64: str | None = Field(None, max_length=MAX_MD_SAMPLES * 11)
    sig: str | None = Field(None, min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")  # HMAC-SHA256 hex

    @field_validator("t")
    @classmethod
    def _plausible_time(cls, v: float) -> float:
        if not (946_684_800.0 <= v <= 4_102_444_800.0):  # 2000-01-01 .. 2100-01-01
            raise ValueError("t must be UNIX epoch seconds between 2000 and 2100")
        return v

    @model_validator(mode="after")
    def _one_geometry(self) -> Detection:
        has_polar = all(v is not None for v in (self.range_m, self.azimuth_deg, self.elevation_deg))
        has_angular = self.range_m is None and self.azimuth_deg is not None and self.elevation_deg is not None
        has_geo = all(v is not None for v in (self.lat, self.lon, self.alt_m))
        if (self.range_m is not None or self.azimuth_deg is not None or self.elevation_deg is not None) and not (
            has_polar or has_angular
        ):
            raise ValueError("angular data needs azimuth_deg and elevation_deg (plus range_m for a polar plot)")
        if any(v is not None for v in (self.lat, self.lon, self.alt_m)) and not has_geo:
            raise ValueError("geodetic measurement needs lat, lon and alt_m together")
        if sum((has_polar, has_angular, has_geo)) != 1:
            raise ValueError("provide exactly one of: polar (range/azimuth/elevation), angular (azimuth/elevation) "
                             "or geodetic (lat/lon/alt)")
        if (self.md_iq_b64 is None) != (self.md_prf_hz is None):
            raise ValueError("md_iq_b64 and md_prf_hz must be provided together")
        return self

    @property
    def geometry(self) -> Literal["polar", "angular", "geodetic"]:
        if self.range_m is not None:
            return "polar"
        return "angular" if self.azimuth_deg is not None else "geodetic"


# --------------------------------------------------------------------------- internal structures


@dataclass(slots=True)
class Measurement:
    """Detection converted to the local ENU frame with its covariance."""

    sensor_id: str
    t: float
    z: NDArray[np.float64]  # (3,) ENU position, metres
    R: NDArray[np.float64]  # (3, 3) position covariance
    kind: SensorKind
    radial_velocity: float | None = None
    rcs_dbsm: float | None = None
    snr_db: float | None = None
    external_id: str | None = None
    md_iq: NDArray[np.complex64] | None = None
    md_prf_hz: float | None = None
    rx_wall: float = 0.0  # wall-clock arrival time, for latency metrics
    geom: Literal["pos", "ang"] = "pos"  # "ang": z = [azimuth rad, elevation rad], bearing-only
    sensor_pos: NDArray[np.float64] | None = None  # sensor ENU position (needed for angle / Doppler updates)
    sigma_rv: float | None = None  # radial-velocity noise; None = Doppler not used


@dataclass(slots=True)
class ClassPosterior:
    """Running class evidence for a track (log-probabilities with exponential forgetting)."""

    classes: tuple[TargetClass, ...] = (TargetClass.drone, TargetClass.bird, TargetClass.clutter)
    logp: NDArray[np.float64] = field(default_factory=lambda: np.zeros(3))
    n: int = 0

    def update(self, probs: NDArray[np.float64], forgetting: float) -> None:
        self.logp = forgetting * self.logp + np.log(np.clip(probs, 1e-6, 1.0))
        self.n += 1

    def probabilities(self) -> NDArray[np.float64]:
        z = self.logp - float(np.max(self.logp))
        p = np.exp(z)
        return np.asarray(p / p.sum())

    def decide(self, threshold: float) -> tuple[TargetClass, float]:
        if self.n == 0:
            return TargetClass.unknown, 0.0
        p = self.probabilities()
        i = int(np.argmax(p))
        if p[i] < threshold:
            return TargetClass.unknown, float(p[i])
        return self.classes[i], float(p[i])


# ---------------------------------------------------------------------------------- API outputs


class TrackOut(BaseModel):
    track_id: str
    seq: int
    status: TrackStatus
    target_class: TargetClass
    class_confidence: float
    confidence: float
    lat: float
    lon: float
    alt_m: float
    east_m: float
    north_m: float
    up_m: float
    vel_e_mps: float
    vel_n_mps: float
    vel_u_mps: float
    speed_mps: float
    heading_deg: float
    climb_mps: float
    rcs_dbsm: float | None
    position_sigma_m: float
    sensors: list[str]
    first_seen: float
    last_seen: float
    age_s: float
    hits: int


class TrackPoint(BaseModel):
    t: float
    lat: float
    lon: float
    alt_m: float
    vel_e_mps: float
    vel_n_mps: float
    vel_u_mps: float
    speed_mps: float
    heading_deg: float
    position_sigma_m: float
    confidence: float
    sensors: list[str]


class AlertOut(BaseModel):
    alert_id: str
    type: AlertType
    level: AlertLevel
    state: Literal["open", "closed"]
    track_id: str
    zone_id: str
    zone_name: str
    opened_at: float
    updated_at: float
    closed_at: float | None
    risk: float = Field(ge=0, le=1)
    target_class: TargetClass
    message: str
    lat: float
    lon: float
    alt_m: float


class Zone(BaseModel):
    """Protected / alert zone: a circle or a polygon, with an altitude band."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    kind: Literal["circle", "polygon"] = "circle"
    center_lat: float | None = Field(None, ge=-90, le=90)
    center_lon: float | None = Field(None, ge=-180, le=180)
    radius_m: float | None = Field(None, gt=0, le=200_000)
    polygon: list[tuple[float, float]] | None = None  # (lat, lon) vertices
    min_alt_m: float = -1000.0
    max_alt_m: float = 100_000.0
    level: AlertLevel = AlertLevel.critical

    @model_validator(mode="after")
    def _shape(self) -> Zone:
        if self.kind == "circle":
            if self.center_lat is None or self.center_lon is None or self.radius_m is None:
                raise ValueError("circle zone needs center_lat, center_lon and radius_m")
        else:
            if not self.polygon or len(self.polygon) < 3:
                raise ValueError("polygon zone needs at least 3 (lat, lon) vertices")
            for lat, lon in self.polygon:
                if not (-90 <= lat <= 90 and -180 <= lon <= 180 and math.isfinite(lat + lon)):
                    raise ValueError("polygon vertex out of range")
        if self.min_alt_m >= self.max_alt_m:
            raise ValueError("min_alt_m must be below max_alt_m")
        return self
