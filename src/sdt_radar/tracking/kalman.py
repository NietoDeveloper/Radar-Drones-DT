"""Constant-velocity Kalman filter primitives (3-D, state = [x y z vx vy vz]).

Process noise is the discretised white-noise-acceleration model with independent horizontal and
vertical intensities. Measurements are ENU positions with a full 3x3 covariance, so polar radar
plots (anisotropic, range-dependent) and geodetic fixes (Remote ID, RF) fuse through the same update.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

F64 = NDArray[np.float64]

_H = np.hstack([np.eye(3), np.zeros((3, 3))])
_I6 = np.eye(6)


def cv_transition(dt: float) -> F64:
    f = np.eye(6)
    f[0, 3] = f[1, 4] = f[2, 5] = dt
    return f


def process_noise(dt: float, sigma_h: float, sigma_v: float) -> F64:
    s2 = np.array([sigma_h**2, sigma_h**2, sigma_v**2])
    q = np.zeros((6, 6))
    for i in range(3):
        q[i, i] = dt**4 / 4.0 * s2[i]
        q[i, i + 3] = q[i + 3, i] = dt**3 / 2.0 * s2[i]
        q[i + 3, i + 3] = dt**2 * s2[i]
    return q


def predict(x: F64, p: F64, dt: float, sigma_h: float, sigma_v: float) -> tuple[F64, F64]:
    f = cv_transition(dt)
    return f @ x, f @ p @ f.T + process_noise(dt, sigma_h, sigma_v)


def update(x: F64, p: F64, z: F64, r: F64) -> tuple[F64, F64, float]:
    """Joseph-form update. Returns (x, P, squared Mahalanobis distance of the innovation)."""
    y = z - _H @ x
    s = _H @ p @ _H.T + r
    k = np.linalg.solve(s.T, (p @ _H.T).T).T
    x_new = x + k @ y
    ikh = _I6 - k @ _H
    p_new = ikh @ p @ ikh.T + k @ r @ k.T
    p_new = 0.5 * (p_new + p_new.T)
    d2 = float(y @ np.linalg.solve(s, y))
    return x_new, p_new, d2


def batch_predict(x: F64, p: F64, dt: F64, sigma_h: float, sigma_v: float) -> tuple[F64, F64]:
    """Vectorised predict for N tracks. x: (N,6), p: (N,6,6), dt: (N,)."""
    n = x.shape[0]
    f = np.broadcast_to(np.eye(6), (n, 6, 6)).copy()
    for i in range(3):
        f[:, i, i + 3] = dt
    xp = np.einsum("nij,nj->ni", f, x)
    s2 = np.array([sigma_h**2, sigma_h**2, sigma_v**2])
    q = np.zeros((n, 6, 6))
    for i in range(3):
        q[:, i, i] = dt**4 / 4.0 * s2[i]
        q[:, i, i + 3] = q[:, i + 3, i] = dt**3 / 2.0 * s2[i]
        q[:, i + 3, i + 3] = dt**2 * s2[i]
    pp = np.einsum("nij,njk,nlk->nil", f, p, f) + q
    return xp, pp


def batch_fq(dt: F64, sigma_h: float, sigma_v: float) -> tuple[F64, F64]:
    """Vectorised transition F (N,6,6) and process noise Q (N,6,6) for N time steps."""
    n = dt.shape[0]
    f = np.broadcast_to(np.eye(6), (n, 6, 6)).copy()
    for i in range(3):
        f[:, i, i + 3] = dt
    s2 = np.array([sigma_h**2, sigma_h**2, sigma_v**2])
    q = np.zeros((n, 6, 6))
    for i in range(3):
        q[:, i, i] = dt**4 / 4.0 * s2[i]
        q[:, i, i + 3] = q[:, i + 3, i] = dt**3 / 2.0 * s2[i]
        q[:, i + 3, i + 3] = dt**2 * s2[i]
    return f, q


def ekf_update(x: F64, p: F64, y: F64, h: F64, r: F64) -> tuple[F64, F64, float, float]:
    """Generic (extended) Kalman update from a linearised measurement.

    ``y`` is the innovation (already wrapped for angles), ``h`` the Jacobian, ``r`` the noise covariance.
    Returns (x, P, d2, log-likelihood); Joseph form keeps ``P`` symmetric positive-definite.
    """
    s = h @ p @ h.T + r
    k = np.linalg.solve(s.T, (p @ h.T).T).T
    x_new = x + k @ y
    ikh = _I6 - k @ h
    p_new = ikh @ p @ ikh.T + k @ r @ k.T
    p_new = 0.5 * (p_new + p_new.T)
    d2 = float(y @ np.linalg.solve(s, y))
    _, logdet = np.linalg.slogdet(2.0 * np.pi * s)
    return x_new, p_new, d2, -0.5 * (d2 + float(logdet))
