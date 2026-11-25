"""Synthetic targets: drones and birds with reproducible, physically plausible trajectories."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

F64 = NDArray[np.float64]


@dataclass
class Trajectory:

    t_end: float = 1e9
    aim = np.array([0.0, 0.0, alt]) if approach else None
    heading = float(np.arctan2(-pos0[0], -pos0[1]) + rng.normal(0, 0.3)) if approach else float(rng.uniform(0, 2 * np.pi))
    traj = make_trajectory(rng, duration, dt, pos0, speed, heading, turn_sigma=0.08, speed_sigma=1.0,
                           climb_sigma=0.4, alt_range=(20, 180), aim_at=aim)
    return Target(f"drone-{idx:03d}", "drone", float(rng.uniform(-23, -17)), traj, cooperative=cooperative,
                  serial=f"1581F{idx:08d}" if cooperative else None, t_start=t_start)


def make_bird(rng: np.random.Generator, idx: int, duration: float, dt: float, *, max_range_m: float) -> Target:
    r = float(rng.uniform(300, max_range_m * 0.8))
    b = float(rng.uniform(0, 2 * np.pi))
    pos0 = np.array([r * np.sin(b), r * np.cos(b), float(rng.uniform(20, 200))])
    speed = float(rng.uniform(6, 14))
    traj = make_trajectory(rng, duration, dt, pos0, speed, float(rng.uniform(0, 2 * np.pi)), turn_sigma=0.35,
                           speed_sigma=1.5, climb_sigma=0.8, alt_range=(10, 250), soar=bool(rng.random() < 0.3),
                           speed_limits=(3.0, 18.0))
    return Target(f"bird-{idx:03d}", "bird", float(rng.uniform(-27, -19)), traj)
