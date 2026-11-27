"""Measurement linearisations for the filter: position, bearing-only (az/el) and Doppler (range-rate).

Each ``*_lin`` returns ``(innovation y, Jacobian H, noise R)`` for a given state ``x``. This is the single
place where a sensor's physics enters the tracker; adding a sensor type means adding a function here.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray

from ..models import Measurement

F64 = NDArray[np.float64]
_H_POS = np.hstack([np.eye(3), np.zeros((3, 3))])


def wrap_pi(a: float) -> float:
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def pos_lin(x: F64, m: Measurement) -> tuple[F64, F64, F64]:
    return m.z - x[:3], _H_POS, m.R


def ang_lin(x: F64, m: Measurement) -> tuple[F64, F64, F64]:
    """Bearing-only: z = [azimuth (rad, clockwise from North), elevation (rad)]."""
    assert m.sensor_pos is not None
    e, n, u = (float(v) for v in (x[:3] - m.sensor_pos))
    rh2 = max(e * e + n * n, 1.0)
    rh = math.sqrt(rh2)
    r2 = rh2 + u * u
    az, el = math.atan2(e, n), math.atan2(u, rh)
    y = np.array([wrap_pi(float(m.z[0]) - az), float(m.z[1]) - el])
    h = np.zeros((2, 6))
    h[0, 0], h[0, 1] = n / rh2, -e / rh2
    h[1, 0], h[1, 1], h[1, 2] = -u * e / (r2 * rh), -u * n / (r2 * rh), rh / r2
    return y, h, m.R


def dop_lin(x: F64, m: Measurement) -> tuple[F64, F64, F64]:
    """Range-rate (radial velocity, positive = receding) as a scalar measurement."""
    assert m.sensor_pos is not None and m.radial_velocity is not None and m.sigma_rv is not None
    rel = x[:3] - m.sensor_pos
    rho = max(float(np.linalg.norm(rel)), 1.0)
    u = rel / rho
    vr = float(u @ x[3:])
    h = np.zeros((1, 6))
    h[0, :3] = (x[3:] - vr * u) / rho
    h[0, 3:] = u
    return np.array([m.radial_velocity - vr]), h, np.array([[m.sigma_rv**2]])
