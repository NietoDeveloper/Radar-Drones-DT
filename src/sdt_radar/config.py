"""Typed configuration, loadable from TOML, with environment overrides for secrets."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import AlertLevel, SensorConfig, Zone


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SiteConfig(_Cfg):
    """Origin of the shared local ENU frame (usually the protected site)."""

    lat: float = Field(4.7110, ge=-90, le=90)
    lon: float = Field(-74.0721, ge=-180, le=180)
    alt_m: float = 2600.0


class TrackerConfig(_Cfg):
    gate_chi2: float = Field(21.1, gt=0, description="Mahalanobis^2 gate (3 dof, 99.99 % = 21.1)")
    confirm_hits: int = Field(5, ge=2)
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
    max_track_speed_mps: float = Field(70.0, gt=0, description="a live track whose speed estimate exceeds this is dropped")
    imm_enabled: bool = Field(True, description="blend a quiet and a manoeuvre model (IMM); False = single model")
    imm_sigma_h_mps2: tuple[float, ...] = (1.5, 8.0)
    imm_sigma_v_mps2: tuple[float, ...] = (1.0, 4.0)
    imm_stay_prob: float = Field(0.95, gt=0.5, lt=1.0)
    use_doppler: bool = Field(True, description="fuse radial velocity (range-rate) when a sensor provides it")
    doppler_gate_chi2: float = Field(9.0, gt=0)
    angle_gate_chi2: float = Field(13.8, gt=0, description="gate for bearing-only updates (2 dof, 99.9 %)")

    @model_validator(mode="after")
    def _ordering(self) -> TrackerConfig:
        if self.max_coast_s <= self.coast_after_s:
            raise ValueError("max_coast_s must exceed coast_after_s")
        if len(self.imm_sigma_h_mps2) != len(self.imm_sigma_v_mps2) or len(self.imm_sigma_h_mps2) < 1:
            raise ValueError("imm_sigma_h_mps2 and imm_sigma_v_mps2 must have the same, non-zero length")
        if any(s <= 0 for s in (*self.imm_sigma_h_mps2, *self.imm_sigma_v_mps2)):
            raise ValueError("IMM sigmas must be positive")
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
    udp_enabled: bool = True    # false: no raw UDP listener (e.g. a hub that only accepts HTTPS from edge nodes)
    tcp_enabled: bool = True
    udp_port: int | None = 9100
    tcp_port: int | None = 9101
    queue_size: int = Field(50_000, ge=1)
    allow_unknown_sensors: bool = False
    require_signatures: bool = Field(False, description="every network detection must carry a valid HMAC signature")
    max_clock_skew_s: float = Field(30.0, gt=0, description="signed detections must be this close to server time")
    default_rate_limit_per_s: float | None = Field(5000.0, gt=0, description="per-sensor cap on the network path")


class StorageConfig(_Cfg):
    kind: str = Field("sqlite", pattern="^(sqlite|memory)$")
    path: str = "data/radar.db"
    point_interval_s: float = Field(1.0, ge=0)
    retention_days: float | None = Field(None, gt=0, description="auto-delete points / closed records older than this")
    recorder_path: str | None = None  # raw detections as JSON-lines, for replay and audit


class ApiKeyConfig(_Cfg):
    """One API key: public id, role and the SHA-256 of its secret (create with ``sdt-radar keygen``)."""

    id: str = Field(pattern="^[A-Za-z0-9-]{1,32}$")
    role: Literal["viewer", "operator", "admin"]
    sha256: str = Field(pattern="^[0-9a-fA-F]{64}$")


class ApiConfig(_Cfg):
    host: str = "127.0.0.1"
    port: int = Field(8080, ge=1, le=65535)
    api_key: str | None = Field(None, description="legacy single admin key; prefer [[api.keys]] (hashed, with roles)")
    keys: list[ApiKeyConfig] = Field(default_factory=list)
    snapshot_hz: float = Field(5.0, gt=0, le=20)
    cors_origins: list[str] = Field(default_factory=list)
    allowed_hosts: list[str] = Field(default_factory=list, description="Host header allow-list ([] = any)")
    rate_limit_per_s: float = Field(50.0, gt=0)
    rate_limit_burst: float = Field(100.0, gt=0)
    lockout_failures: int = Field(8, ge=1)
    lockout_window_s: float = Field(60.0, gt=0)
    lockout_s: float = Field(300.0, gt=0)
    ws_ticket_ttl_s: float = Field(30.0, gt=0, le=300)
    allow_query_api_key: bool = Field(False, description="accept ?api_key= on the WebSocket (leaks into URLs/logs)")
    max_body_bytes: int = Field(5_000_000, ge=1_000)
    trust_proxy_headers: bool = Field(False, description="derive the client IP from X-Forwarded-For (only behind your proxy)")
    metrics_public: bool = Field(False, description="serve /metrics without a key (e.g. scraped inside a private network)")
    tls_certfile: str | None = None
    tls_keyfile: str | None = None

    @model_validator(mode="after")
    def _keys(self) -> ApiConfig:
        ids = [k.id for k in self.keys]
        if len(ids) != len(set(ids)):
            raise ValueError("api key ids must be unique")
        if bool(self.tls_certfile) != bool(self.tls_keyfile):
            raise ValueError("tls_certfile and tls_keyfile must be set together")
        return self


class AuditConfig(_Cfg):
    enabled: bool = True
    path: str = "data/audit.jsonl"
    max_per_min: int = Field(30, ge=1, description="per-action cap so floods cannot fill the disk")


class LoggingConfig(_Cfg):
    format: Literal["text", "json"] = "text"
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class WebhookConfig(_Cfg):
    url: str = Field(pattern="^https?://")
    secret_env: str | None = Field(None, max_length=128, description="env var with the HMAC secret for X-SDT-Signature")
    min_level: AlertLevel = AlertLevel.warning
    timeout_s: float = Field(5.0, gt=0, le=60)
    retries: int = Field(3, ge=0, le=10)


class NotifyConfig(_Cfg):
    webhooks: list[WebhookConfig] = Field(default_factory=list)


class AlertConfig(_Cfg):
    lookahead_s: float = Field(30.0, ge=0)
    clear_after_s: float = Field(5.0, ge=0)
    suppress_class_above: float = Field(0.9, ge=0.5, le=1.0, description="bird/clutter at/above this confidence: no alerts")


class Settings(_Cfg):
    site: SiteConfig = SiteConfig()
    sensors: list[SensorConfig] = Field(default_factory=list)
    zones: list[Zone] = Field(default_factory=list)
    tracker: TrackerConfig = TrackerConfig()
    classifier: ClassifierConfig = ClassifierConfig()
    fusion: FusionConfig = FusionConfig()
    ingest: IngestConfig = IngestConfig()
    storage: StorageConfig = StorageConfig()
    api: ApiConfig = ApiConfig()
    alerts: AlertConfig = AlertConfig()
    audit: AuditConfig = AuditConfig()
    logging: LoggingConfig = LoggingConfig()
    notify: NotifyConfig = NotifyConfig()

    @model_validator(mode="after")
    def _unique_ids(self) -> Settings:
        ids = [s.id for s in self.sensors]
        if len(ids) != len(set(ids)):
            raise ValueError("sensor ids must be unique")
        zids = [z.id for z in self.zones]
        if len(zids) != len(set(zids)):
            raise ValueError("zone ids must be unique")
        return self


def load_settings(path: str | Path | None = None) -> Settings:
    """Load settings from a TOML file (or defaults). ``SDT_RADAR_API_KEY`` overrides ``api.api_key``."""
    data: dict = {}
    if path is not None:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    settings = Settings.model_validate(data)
    key = os.environ.get("SDT_RADAR_API_KEY")
    if key:
        settings.api.api_key = key
    return settings
