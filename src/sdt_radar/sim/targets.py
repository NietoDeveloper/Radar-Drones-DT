"""Synthetic targets: drones and birds with reproducible, physically plausible trajectories."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

F64 = NDArray[np.float64]


@dataclass
class Trajectory:
