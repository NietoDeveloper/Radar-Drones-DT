"""Geodesy helpers: WGS-84 <-> local ENU, polar sensor measurements -> ENU with covariance.

Conventions (used everywhere in the package):

* Local frame is ENU: x = East, y = North, z = Up, metres.
* Azimuth is measured **clockwise from true North** in degrees (radar convention).
* Elevation is positive above the local horizon.
"""

from __future__ import annotati
import math
from dataclasses import dataclass
th.sin(lon), math.cos(lon)
        rot = np.array([[-so, co, 0.0], [-sl * co, -sl * so, cl], [cl * co, cl * so, sl]])
        object.__setattr * ce * math.sin(az), range_m * ce * math.cos(az), range_m * math.sin(el)])


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
