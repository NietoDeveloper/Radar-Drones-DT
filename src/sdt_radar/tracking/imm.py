"""Interacting Multiple Model (IMM) estimator over constant-velocity models with different manoeuvre noise.

A "quiet" model (low acceleration noise) gives sharp estimates for steady flight; a "manoeuvre" model
(high noise) follows turns and speed changes. The IMM blends them by how well each explains the data,
which removes the classic trade-off of a single process-noise setting (tight gates break on turns, loose
ones add noise). One vectorised implementation serves both association (N tracks) and update (N = 1).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np
from numpy.typing import NDArray

from ..models import Measurement
from . import kalman

F64 = NDArray[np.float64]
Linearise = Callable[[F64, Measurement], tuple[F64, F64, F64]]


class Imm:
    def __init__(self, sigmas_h: Sequence[float], sigmas_v: Sequence[float], stay_prob: float = 0.95) -> None:
        assert len(sigmas_h) == len(sigmas_v) >= 1
        self.m = len(sigmas_h)
        self.sigmas_h, self.sigmas_v = tuple(sigmas_h), tuple(sigmas_v)
        # `stay_prob` is the probability of staying in a model over ONE SECOND. The transition matrix over
        # dt seconds is T(dt) = U + lam^dt (I - U), U = 11'/M, lam = (M*stay - 1)/(M - 1): the exact
        # fractional power of the symmetric stay/switch matrix, so switching rate does not depend on how
        # many sensors update the track per second (and dt = 0 means no transition at all).
        self.lam = (self.m * stay_prob - 1.0) / (self.m - 1.0) if self.m > 1 else 1.0
        mu0 = np.full(self.m, 0.3 / max(self.m - 1, 1))
        mu0[0] = 1.0 - mu0[1:].sum()
        self.mu0 = mu0 if self.m > 1 else np.ones(1)

    # ------------------------------------------------------------------------------- predict
    def predict(self, xs: F64, ps: F64, mu: F64, dt: F64) -> tuple[F64, F64, F64]:
        """Mix then predict. xs (N,M,6), ps (N,M,6,6), mu (N,M), dt (N,). Returns xp, Pp, c (N,M)."""
        u = np.full((self.m, self.m), 1.0 / self.m)
        t = u[None] + (self.lam ** dt)[:, None, None] * (np.eye(self.m) - u)[None]  # (N,M,M)
        c = np.maximum(np.einsum("ni,nij->nj", mu, t), 1e-12)  # predicted model probabilities (N,M)
        mix = mu[:, :, None] * t / c[:, None, :]  # mixing weights mu_{i|j}  (N,i,j)
        x0 = np.einsum("nij,nid->njd", mix, xs)
        dx = xs[:, :, None, :] - x0[:, None, :, :]  # (N,i,j,6)
        p0 = np.einsum("nij,nijab->njab", mix, ps[:, :, None] + dx[..., :, None] * dx[..., None, :])
        xp = np.empty_like(x0)
        pp = np.empty_like(p0)
        for j in range(self.m):
            f, q = kalman.batch_fq(dt, self.sigmas_h[j], self.sigmas_v[j])
            xp[:, j] = np.einsum("nab,nb->na", f, x0[:, j])
            pp[:, j] = np.einsum("nab,nbc,ndc->nad", f, p0[:, j], f) + q
        return xp, pp, c

    @staticmethod
    def combine(w: F64, xs: F64, ps: F64) -> tuple[F64, F64]:
        """Moment-matched mixture of the model estimates with weights w (N,M)."""
        x = np.einsum("nm,nmd->nd", w, xs)
        dx = xs - x[:, None, :]
        p = np.einsum("nm,nmab->nab", w, ps + dx[..., :, None] * dx[..., None, :])
        return x, 0.5 * (p + p.transpose(0, 2, 1))

    # -------------------------------------------------------------------------------- update
    def update(self, xp: F64, pp: F64, c: F64, meas: Sequence[tuple[Linearise, Measurement, float | None]]
               ) -> tuple[F64, F64, F64]:
        """Update one track's models (xp (M,6), pp (M,6,6), c (M,)) with measurements.

        Each measurement is ``(linearise, data, gate_chi2)``; a gate of ``None`` always applies, a number
        skips that measurement for a model whose innovation exceeds it (protects against bad Doppler).
        Returns the new (xs, Ps, mu).
        """
        xs, ps = xp.copy(), pp.copy()
        logl = np.zeros(self.m)
        for j in range(self.m):
            x, p = xs[j], ps[j]
            for lin, m, gate in meas:
                y, h, r = lin(x, m)
                if gate is not None:
                    s = h @ p @ h.T + r
                    if float(y @ np.linalg.solve(s, y)) > gate:
                        continue
                x, p, _, ll = kalman.ekf_update(x, p, y, h, r)
                logl[j] += ll
            xs[j], ps[j] = x, p
        w = np.log(np.maximum(c, 1e-12)) + logl
        w = np.exp(w - np.max(w))
        mu = np.maximum(w / w.sum(), 1e-3)
        return xs, ps, mu / mu.sum()
