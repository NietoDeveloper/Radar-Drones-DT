"""Track object: filter state + lifecycle + bookkeeping (history, class evidence, sensors)."""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from ..models import ClassPosterior, TrackStatus

F64 = NDArray[np.float64]


@dataclass(slots=True)
class HistoryPoint:
    t: float
    x: F64  # (6,) ENU state
    pos_sigma: float
    confidence: float
    sensors: tuple[str, ...]


@dataclass(slots=True)
class Track:
    seq: int
    x: F64  # (6,) state at time `t`
    P: F64  # (6,6)
    t: float  # time of the state (last update)
    first_t: float
    track_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: TrackStatus = TrackStatus.tentative
    hits: int = 1
    last_hit_t: float = 0.0
    sensors: dict[str, float] = field(default_factory=dict)  # sensor_id -> last update time
    external_ids: set[str] = field(default_factory=set)
    rcs_dbsm: float | None = None
    klass: ClassPosterior = field(default_factory=ClassPosterior)
    history: deque[HistoryPoint] = field(default_factory=deque)
    last_hist_t: float = -1e18
    stored_t: float = -1e18  # last time a point was handed to storage
    announced: bool = False  # confirmation event already emitted
    # IMM model bank (xs (M,6), Ps (M,6,6), mu (M,)); `x`/`P` above are always the fused estimate.
    xs: F64 | None = None
    Ps: F64 | None = None
    mu: F64 | None = None

    def ensure_models(self, m: int, mu0: F64) -> None:
        if self.xs is None or self.xs.shape[0] != m:
            self.xs = np.repeat(self.x[None], m, axis=0)
            self.Ps = np.repeat(self.P[None], m, axis=0)
            self.mu = mu0.copy()

    # ---- derived quantities -------------------------------------------------------------------
    @property
    def pos(self) -> F64:
        return self.x[:3]

    @property
    def vel(self) -> F64:
        return self.x[3:]

    @property
    def position_sigma(self) -> float:
        return float(np.sqrt(np.trace(self.P[:3, :3]) / 3.0))

    def confidence(self, now: float, max_coast_s: float) -> float:
        """Heuristic existence score in [0, 1] (NOT a calibrated probability).

        Grows with the number of supporting measurements (saturating), decays while the track
        is coasting and when the position uncertainty is large.
        """
        support = 1.0 - 0.5 ** max(self.hits - 1, 0)
        fresh = max(0.0, 1.0 - max(now - self.last_hit_t, 0.0) / max_coast_s)
        return float(np.clip(support * (0.4 + 0.6 * fresh), 0.0, 1.0))

    def sensor_list(self) -> list[str]:
        return sorted(self.sensors)
