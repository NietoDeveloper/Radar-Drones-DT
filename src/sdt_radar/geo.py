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