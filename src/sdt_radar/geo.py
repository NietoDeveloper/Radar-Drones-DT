"""Geodesy helpers: WGS-84 <-> local ENU, polar sensor measurements -> ENU with covariance.

Conventions (used everywhere in the package):

* Local frame is ENU: x = East, y = North, z = Up, metres.
* Azimuth is measured **clockwise from true North** in degrees (radar convention).
* Elevation is positive above the local horizon.
"""
