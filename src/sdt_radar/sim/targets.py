"""Synthetic targets: drones and birds with reproducible, physically plausible trajectories."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

F64 = NDArray[np.float64]


@dataclass
class Trajectory:

@dataclass
class Target:
    target_id: str
    kind: str  # "drone" | "bird"
    rcs_dbsm: float  # mean RCS
    traj: Trajectory
    cooperative: bool = False  # broadcasts Remote ID
    serial: str | None = None
    t_start: float = 0.0
    t_end: float = 1e9

    def active(self, t: float) -> bool:
        return self.t_start <= t <= self.t_end


def _wrap(a: float) -> float:
    return (a + np.pi) % (2 * np.pi) - np.pi


def make_trajectory(rng: np.random.Generator, duration: float, dt: float, pos0: F64, speed: float,
                    heading: float, *, turn_sigma: float, speed_sigma: float, climb_sigma: float,
                    alt_range: tuple[float, float], aim_at: F64 | None = None, soar: bool = False, loiter_radius_m: float = 200.0,
                    speed_limits: tuple[float, float] = (2.0, 30.0)) -> Trajectory:
    n = int(duration / dt) + 1
    t = np.arange(n, dtype=float) * dt
    pos = np.zeros((n, 3))
    vel = np.zeros((n, 3))
    pos[0] = pos0
    h, v, vz = heading, speed, 0.0
    turn_bias = rng.choice([-0.4, 0.4]) if soar else 0.0
    for i in range(n):
        vel[i] = (v * np.sin(h), v * np.cos(h), vz)  # heading clockwise from North
        if i + 1 < n:
            pos[i + 1] = pos[i] + vel[i] * dt
            if aim_at is not None:
                d = aim_at - pos[i]
                if float(np.hypot(d[0], d[1])) < loiter_radius_m:  # reached the objective: orbit it
                    turn = v / loiter_radius_m
                else:
                    bearing = np.arctan2(d[0], d[1])
                    turn = float(np.clip(0.8 * _wrap(bearing - h), -0.6, 0.6))
            else:
                turn = turn_bias + rng.normal(0, turn_sigma)
            h += turn * dt
            v = float(np.clip(v + rng.normal(0, speed_sigma) * dt, *speed_limits))
            z = pos[i + 1, 2]
            target_vz = np.clip(0.2 * (np.mean(alt_range) - z), -3, 3)
            vz += 0.5 * (target_vz - vz) * dt + rng.normal(0, climb_sigma) * dt
            if z < alt_range[0] or z > alt_range[1]:
                vz = float(np.clip(0.3 * (np.mean(alt_range) - z), -3, 3))
    return Trajectory(t, pos, vel)


def make_drone(rng: np.random.Generator, idx: int, duration: float, dt: float, *, approach: bool,
               bearing_deg: float, start_range_m: float, cooperative: bool, site_alt: float = 0.0,
               t_start: float = 0.0) -> Target:
    b = np.radians(bearing_deg)
    alt = float(rng.uniform(40, 150))
    pos0 = np.array([start_range_m * np.sin(b), start_range_m * np.cos(b), alt])
    speed = float(rng.uniform(6, 22))
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
