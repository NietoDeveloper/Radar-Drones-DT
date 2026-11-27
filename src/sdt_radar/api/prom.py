"""Prometheus text exposition (format 0.0.4) of the pipeline's health, with no extra dependency."""

from __future__ import annotations

import time
from typing import Any


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render(metrics: dict[str, Any], ws: dict[str, int], started: float, audit_suppressed: int = 0,
           webhook: dict[str, int] | None = None) -> str:
    lines: list[str] = []

    def metric(name: str, help_: str, typ: str, samples: list[tuple[dict[str, str], float]]) -> None:
        lines.append(f"# HELP {name} {help_}")
        lines.append(f"# TYPE {name} {typ}")
        for labels, value in samples:
            lab = ",".join(f'{k}="{_esc(v)}"' for k, v in labels.items())
            lines.append(f"{name}{{{lab}}} {value}" if lab else f"{name} {value}")

    c = metrics["counters"]
    metric("sdt_tracks", "Live tracks by status.", "gauge",
           [({"status": k}, v) for k, v in sorted(metrics["tracks_by_status"].items())] or [({"status": "none"}, 0)])
    metric("sdt_detections_received_total", "Detections accepted by ingest.", "counter", [({}, c.get("received", 0))])
    metric("sdt_detections_rejected_total", "Detections rejected, by reason.", "counter",
           [({"reason": k.removeprefix("rejected_")}, v) for k, v in sorted(c.items()) if k.startswith("rejected_")]
           or [({"reason": "none"}, 0)])
    metric("sdt_stale_measurements_total", "Measurements older than the track state.", "counter",
           [({}, c.get("stale_measurements", 0))])
    metric("sdt_tracker_events_total", "Tracker lifecycle events.", "counter",
           [({"event": k}, v) for k, v in sorted(metrics["tracker"].items())])
    for key, name in (("latency_ms", "sdt_ingest_latency_ms"), ("step_ms", "sdt_step_ms")):
        metric(name, f"{key} quantiles (rolling window).", "gauge",
               [({"quantile": q[1:]}, v) for q, v in metrics[key].items() if v is not None])
    metric("sdt_reorder_buffer_items", "Measurements waiting in the reorder buffer.", "gauge", [({}, metrics["buffer_len"])])
    metric("sdt_reorder_buffer_dropped_total", "Measurements shed by back-pressure.", "counter",
           [({}, metrics["buffer_dropped"])])
    now = time.time()
    metric("sdt_sensor_last_seen_age_seconds", "Seconds since a sensor last delivered data.", "gauge",
           [({"sensor": sid}, round(now - st["last_rx"], 3)) for sid, st in sorted(metrics["sensors"].items()) if st["last_rx"]])
    metric("sdt_ws_clients", "Connected WebSocket clients.", "gauge", [({}, ws["clients"])])
    metric("sdt_ws_snapshots_total", "WebSocket snapshots published.", "counter", [({}, ws["published"])])
    metric("sdt_ws_dropped_total", "WebSocket messages dropped for slow clients.", "counter", [({}, ws["dropped"])])
    metric("sdt_audit_suppressed_total", "Audit records suppressed by the flood cap.", "counter", [({}, audit_suppressed)])
    if webhook is not None:
        metric("sdt_webhook_total", "Webhook deliveries by outcome.", "counter",
               [({"outcome": k}, v) for k, v in sorted(webhook.items())])
    metric("sdt_uptime_seconds", "Process uptime.", "gauge", [({}, round(now - started, 1))])
    return "\n".join(lines) + "\n"
