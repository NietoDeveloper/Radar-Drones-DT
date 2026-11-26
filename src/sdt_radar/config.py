"""Typed configuration, loadable from TOML, with environment overrides for secrets."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import SensorConfig, Zone


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid")


    gate_chi2: float = Field(21.1, gt=0, description="Mahalanobis^2 gate (3 dof, 99.99 % = 21.1)")
    confirm_hits: int = Field(4, ge=2)
    confirm_window_s: float = Field(12.0, gt=0)
    tentative_timeout_s: float = Field(4.0, gt=0)
