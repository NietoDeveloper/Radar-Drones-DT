"""Scenarios (targets + sensors), detection-stream generation and an offline runner with scoring."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..config import Settings, SiteConfig
from ..geo import LocalFrame
from ..models import AlertLevel, Detect