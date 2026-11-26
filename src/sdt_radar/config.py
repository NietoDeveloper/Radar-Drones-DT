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
    merge_distance_m: float = Field(15.0, ge=0)
    merge_speed_diff_mps: float = Field(5.0, ge=0)
    merge_chi2: float = Field(16.8, ge=0, description="statistical merge gate on the 6-D state difference (0 disables)")
    max_confirm_speed_mps: float = Field(50.0, gt=0, description="speed estimate above this blocks confirmation")

    @model_validator(mode="after")
    def _ordering(self) -> TrackerConfig:
        if self.max_coast_s <= self.coast_after_s:
            raise ValueError("max_coast_s must exceed coast_after_s")
        return self


class ClassifierConfig(_Cfg):
    enabled: bool = True
    model_path: str | None = None  # None = packaged model
    decision_threshold: float = Field(0.7, ge=0.34, le=1.0)
    forgetting: float = Field(0.92, gt=0, le=1.0)


class FusionConfig(_Cfg):
    reorder_window_s: float = Field(0.2, ge=0)
    batch_bucket_s: float = Field(0.25, gt=0)


class IngestConfig(_Cfg):
    host: str = "127.0.0.1"
    udp_port: int | None = 9100
    tcp_port: int | None = 9101
    queue_size: int = Field(50_000, ge=1)
    allow_unknown_sensors: bool = False


class StorageConfig(_Cfg):
    kind: str = Field("sqlite", pattern="^(sqlite|memory)$")
    path: str = "data/radar.db"
    point_interval_s: float = Field(1.0, ge=0)
    recorder_path: str | None = None  # raw detections as JSON-lines, for replay and audit


class ApiConfig(_Cfg):
    host: str = "127.0.0.1"
    port: int = Field(8080, ge=1, le=65535)
    api_key: str | None = None
    snapshot_hz: float = Field(5.0, gt=0, le=20)
    cors_origins: list[str] = Field(default_factory=list)
