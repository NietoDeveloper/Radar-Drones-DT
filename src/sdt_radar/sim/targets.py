"""Synthetic targets: drones and birds with reproducible, physically plausible trajectories."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

F64 = NDArray[np.float64]


@dataclass
class Trajectory:

    t_end: float = 1e9
def make_bird(rng: np.random.Generator, idx: int, duration: float, dt: float, *, max_range_m: float) -> Target:
    r = float(rng.uniform(300, max_range_m * 0.8))
    b = float(rng.uniform(0, 2 * np.pi))
    pos0 = np.array([r * np.sin(b)