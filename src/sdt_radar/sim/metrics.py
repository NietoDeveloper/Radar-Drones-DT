"""Scoring of tracker output against simulation ground truth."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linea
    if not confirmed:
        return
    tp = np.array([[t.east_m, 