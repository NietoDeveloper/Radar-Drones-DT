"""Scale benchmark: hundreds of simultaneous tracks through the full pipeline (data time)."""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from .sim import generate, run_scenario, swarm_scenario

