"""Scenarios (targets + sensors), detection-stream generation and an offline runner with scoring."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..config import Settings, SiteConfig
from ..geo import LocalFrame
from ..models import AlertLevel, Detection, SensorConfig, SensorKind, Zone
from ..pipeline import Pipeline
from .metrics import Score, evaluate_snapshot
from .sensors import FixModel, RadarModel
from .targets import Target, make_bird, make_drone

    def settings(self, **overrides: object) -> Settings:
        data = {"site": self.site, "sensors": self.sensor_configs(), "zones": self.zones,
                "storage": {"kind": 