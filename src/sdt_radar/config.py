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
    coast_after_s: float = Field(2.0, gt=0)
    max_coast_s: float = Field(8.0, gt=0)
    sigma_accel_h_mps2: float = Field(4.0, gt=0)
    sigma_accel_v_mps2: float = Field(2.5, gt=0)
    init_velocity_sigma_mps: float = Field(20.0, gt=0)
    max_tracks: int = Field(2000, ge=1)
    history_len: int = Field(600, ge=1)
    history_min_dt_s: float = Field(0.5, ge=0)
