"""Geodesy helpers: WGS-84 <-> local ENU, polar sensor measurements -> ENU with covariance.

Conventions (used everywhere in the package):

* Local frame is ENU: x = East, y = North, z = Up, metres.
* Azimuth is measured **clockwise from true North** in degrees (radar convention).
* Elevation is positive above the local horizon.
"""

from __future__ import annotati
import math
from dataclasses import dataclass

import n
from numpy.typing import ArrayLike, NDArray

WGS84_A = 6_378_137.0
WGS84_F = 1.0 / 298.2
WGS84_E2 = WGS84_F * (2.0 
def geodetic_to_ecef(lat_deg: ArrayLike, loeLike, alt_m: ArrayLike) -> FloatArray:
    lat = np.radians(np.asarray(lat_deg, dtype=float))
    lon = np.radians(np.asarray(lon_dege=float))
    alt = np.asarray(alt_m, dtype=float)
    s, c = np.sin(lat), np.cos(lat)
    n = WGS84_A / np.sqrt(1.0 - WGS84_E2 * s * s)
    x = (n + alt) * c * np.cos(lon)
    y = (n + alt) * c * np.sin(lon)
    z = (n * (1.0 - WGS84_E2) + alt) * s
    return np.stack([x, y, z], axis=-1)


def ecef_to_geodetic(xyz: ArrayLike) -> tuple[FloatArray, FloatArray, FloatArray]:
    a = np.asarray(xyz, dtype=float)
    x, y, z = a[..., 0], a[..., 1], a[..., 2]
    lon = np.arctan2(y, x)
    p = np.hypot(x, y)
    lat = np.arctan2(z, p * (1.0 - WGS84_E2))
    for _ in range(6):
        s = np.sin(lat)
        n = WGS84_A / np.sqrt(1.0 - WGS84_E2 * s * s)
        alt = p / np.maximum(np.cos(lat), 1e-12) - n
        lat = np.arctan2(z, p * (1.0 - WGS84_E2 * n / (n + alt)))
    s = np.sin(lat)
    n = WGS84_A / np.sqrt(1.0 - WGS84_E2 * s * s)
    alt = p / np.maximum(np.cos(lat), 1e-12) - n
    return np.degrees(lat), np.degrees(lon), alt


@dataclass(frozen=True)
class LocalFrame:
    """East-North-Up frame anchored at a geodetic origin."""

    lat: float
    lon: float
    alt_m: float = 0.0

    def __post_init__(self) -> None:
        lat, lon = math.radians(self.lat), math.radians(self.lon)
        sl, cl, so, co = math.sin(lat), math.cos(lat), math.sin(lon), math.cos(lon)
        rot = np.array([[-so, co, 0.0], [-sl * co, -sl * so, cl], [cl * co, cl * so, sl]])
        object.__setattr__(self, "_rot", rot)
        object.__setattr__(self, "_ecef0", geodetic_to_ecef(self.lat, self.lon, self.alt_m))

    def to_enu(self, lat: ArrayLike, lon: ArrayLike, alt_m: ArrayLike) -> FloatArray:
        ecef = geodetic_to_ecef(lat, lon, alt_m)
        return np.asarray((ecef - self._ecef0) @ self._rot.T)  # type: ignore[attr-defined]

    def to_geodetic(self, enu: ArrayLike) -> tuple[FloatArray, FloatArray, FloatArray]:
        e = np.asarray(enu, dtype=float)
        ecef = self._ecef0 + e @ self._rot  # type: ignore[attr-defined]
        return ecef_to_geodetic(ecef)


def polar_to_enu(range_m: float, az_deg: float, el_deg: float) -> FloatArray:
    """Sensor-relative polar -> ENU offset (azimuth clockwise from North)."""
    az, el = math.radians(az_deg), math.radians(el_deg)
    ce = math.cos(el)
    return np.array([range_m * ce * math.sin(az), range_m * ce * math.cos(az), range_m * math.sin(el)])


def polar_covariance(
    range_m: float, az_deg: float, el_deg: float, sigma_r: float, sigma_az_deg: float, sigma_el_deg: float
) -> FloatArray:
    """Cartesian covariance of a polar measurement (first-order Jacobian propagation)."""
    az, el = math.radians(az_deg), math.radians(el_deg)
    sa, ca, se, ce = math.sin(az), math.cos(az), math.sin(el), math.cos(el)
    jac = np.array(
        [
            [ce * sa, range_m * ce * ca, -range_m * se * sa],
            [ce * ca, -range_m * ce * sa, -range_m * se * ca],
            [se, 0.0, range_m * ce],
        ]
    )
    var = np.diag([sigma_r**2, math.radians(sigma_az_deg) ** 2, math.radians(sigma_el_deg) ** 2])
    return np.asarray(jac @ var @ jac.T)


def enu_to_polar(enu: ArrayLike) -> tuple[float, float, float]:
    """ENU offset -> (range, azimuth_deg in [0, 360), elevation_deg)."""
    e, n, u = (float(v) for v in np.asarray(enu, dtype=float))
    rng = math.sqrt(e * e + n * n + u * u)
    az = math.degrees(math.atan2(e, n)) % 360.0
    el = math.degrees(math.atan2(u, math.hypot(e, n)))
    return rng, az, el


def heading_deg(ve: float, vn: float) -> float:
    """Course over ground, degrees clockwise from North in [0, 360)."""
    return math.degrees(math.atan2(ve, vn)) % 360.0
