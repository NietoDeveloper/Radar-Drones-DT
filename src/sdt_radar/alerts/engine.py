"""Zone intrusion / approach alerting with hysteresis and a transparent risk score.

* ``zone_intrusion``: a live track is inside a zone (horizontal shape + altitude band).
* ``zone_approach``: straight-line extrapolation of the track enters a zone within ``lookahead_s``.

Alerts are *stateful*: one open alert per (track, zone, type); closed after the condition has been
absent for ``clear_after_s`` or when the track is lost. Bird/clutter tracks classified with high
confidence are suppressed (``suppress_class_above``) to cut false alarms.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import d
import numpy as
from ..config import AlertConfig
from ..geo import LocalFrame
from ..models import AlertLevel, AlertOut, Alert, TargetClass, TrackStatus, Zone
from ..tracking.track import 
_CLASS_WEIGHT = {TargetClass.drone: 1.0, Target.unk
    def __