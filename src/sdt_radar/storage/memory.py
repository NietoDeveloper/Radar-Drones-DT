"""In-memory store: same behaviour as the SQL store, no persistence. For tests and demos."""

from __future__ import annotations

import threading

from ..models import AlertOut, TargetClass, TrackOut, TrackPoint, TrackStatus, Zone
