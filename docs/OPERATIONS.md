# Operations guide

## 1. Deployment

| Option | Command | Notes |
|---|---|---|
| Virtualenv | `pip install . && sdt-radar serve --config /etc/sdt-radar/radar.toml` | Simplest; runs on one core of any Linux/macOS/Windows host with Python ≥ 3.11 |
| systemd | unit below | Restarts on failure, journald logs |
| Docker | `docker build -t sdt-drone-radar .` then `docker run -e SDT_RADAR_API_KEY=… -p 8080:8080 -p 9100:9100/udp -p 9101:9101 -v radar-data:/data …` | Dockerfile provided; **not built in the authoring environment** — verify before relying on it. Set `storage.path = "/data/radar.db"` in the config you mount |

```ini
# /etc/systemd/system/sdt-radar.service   (illustrative, untested)
[Unit]
Description=SoftwareDT drone radar backend
After=network-online.target
[Service]
User=radar
Environment=SDT_RADAR_API_KEY=change-me
ExecStart=/opt/sdt-radar/venv/bin/sdt-radar serve --config /etc/sdt-radar/radar.toml
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/sdt-radar
[Install]
WantedBy=multi-user.target
```

Ports: **8080** API + WebSocket, **9100/udp** and **9101/tcp** detection ingest (all configurable).

## 2. Security

The full model, role matrix and hardening checklist are in [SECURITY.md](SECURITY.md). Operational minimum:

1. `sdt-radar keygen --role viewer|operator|admin --id <name>` per client; store tokens in a secret manager;
   put only the printed `[[api.keys]]` record (a hash) in the config. The CLI refuses to bind a non-loopback
   address without keys.
2. TLS: `--tls-cert/--tls-key` or a reverse proxy. Behind a proxy set `api.trust_proxy_headers = true` (and only then).
3. Sign every sensor that sends over UDP/TCP; `require_signatures = true`; firewall 9100/udp and 9101/tcp.
4. Keep NTP/PTP healthy on every host: signature verification depends on a ±30 s clock window.
5. Back up `data/audit.jsonl`, run `sdt-radar audit-verify` on a schedule, and anchor `GET /api/v1/audit/head`.

## 3. Monitoring

`GET /api/v1/metrics` (JSON). Alert on:

| Signal | Meaning | Action |
|---|---|---|
| `counters.rejected_invalid / rejected_sensor / rejected_malformed` rising | Adapter bug, wrong sensor id, garbage on the port | Fix adapter / registration / firewall |
| `rejected_bad_signature`, `rejected_replay`, `rejected_unsigned` > 0 (also in the audit log) | Wrong secret, captured traffic being replayed, spoofing attempt | Check the sensor secret; investigate the source IP; tighten the firewall |
| `rejected_skew` rising | A signed sensor's clock is off by > 30 s | Fix NTP/PTP on that sensor |
| `rejected_rate` rising | A sensor (or attacker) exceeds its rate limit | Raise `rate_limit_per_s` if legitimate; otherwise block |
| HTTP 429 / `auth_failure` audit events | Rate limiting or brute-force lockout | Identify the client; rotate the key if it leaked |
| `counters.stale_measurements` rising | A sensor clock is behind or its path is reordering heavily | Check NTP; raise `fusion.reorder_window_s` |
| `buffer_dropped > 0` | Backlog beyond `ingest.queue_size` | Find the flood; check CPU |
| `latency_ms.p99` > 400 | Pipeline or event loop saturated, or a sensor clock ahead | Check `step_ms`, CPU, clock skew |
| `step_ms.p99` approaching the scan period | Too many tracks per core | Reduce load / raise gate efficiency / scale out (roadmap) |
| `tracker.dropped_capacity > 0` | `max_tracks` reached | Raise `tracker.max_tracks` or investigate clutter storm |
| `tracks_by_status.tentative` consistently large | Clutter / false-alarm storm | Tune the radar CFAR, raise `confirm_hits` |
| `sensors[*].last_rx` stale (`/api/v1/sensors` `last_seen_age_s`) | Sensor or network down | Check the sensor |
| `ws.dropped` rising | Slow WebSocket clients | Fix the client / network |
| `counters.step_errors` > 0 | An unexpected exception in a pipeline step (logged) | Read the server log |

`GET /health` is for load balancers (always open).

### 3.1 Prometheus

`GET /metrics` (viewer key, or no key if `api.metrics_public`) serves the standard text format:
`sdt_tracks{status}`, `sdt_detections_received_total`, `sdt_detections_rejected_total{reason}`,
`sdt_tracker_events_total{event}`, `sdt_ingest_latency_ms{quantile}`, `sdt_step_ms{quantile}`,
`sdt_reorder_buffer_items`, `sdt_sensor_last_seen_age_seconds{sensor}`, `sdt_ws_clients`, `sdt_webhook_total{outcome}`,
`sdt_audit_suppressed_total`, `sdt_uptime_seconds`.

```yaml
# prometheus.yml
scrape_configs:
  - job_name: sdt-radar
    scheme: https
    tls_config: { ca_file: /etc/prometheus/radar-ca.pem }
    authorization: { type: Bearer, credentials_file: /etc/prometheus/radar-key }   # see note
    static_configs: [{ targets: ["radar-hub:8443"] }]
```
Note: the API reads the `X-API-Key` header; Prometheus sends custom headers via `http_headers`
(Prometheus ≥ 2.50) or through a small proxy. Use a **viewer** key.

Useful alert rules: `increase(sdt_detections_rejected_total{reason=~"bad_signature|replay"}[5m]) > 0`,
`sdt_sensor_last_seen_age_seconds > 30`, `sdt_ingest_latency_ms{quantile="0.99"} > 400`.

### 3.2 Structured logs

`[logging] format = "json"` emits one JSON object per line with `request_id` (the `X-Request-ID` of the
request, echoed in the response) so a client report can be traced through the logs.

### 3.3 Webhooks

```toml
[[notify.webhooks]]
url = "https://hooks.example.com/radar"
secret_env = "SDT_WEBHOOK_SECRET"
min_level = "warning"        # info | warning | critical
```
Receivers verify `X-SDT-Signature` (`sha256=` + HMAC-SHA256 of `X-SDT-Timestamp + "." + body`) and reject old
timestamps. Delivery is asynchronous, retried with back-off, bounded (drops counted in `sdt_webhook_total`).

## 4. Tuning guide

| Symptom | Likely cause | Knob |
|---|---|---|
| Tracks fragment on manoeuvres (ID switches) | Gate too tight / process noise too low | `tracker.gate_chi2` ↑ (21.1 → 25), `sigma_accel_h_mps2` ↑ |
| Two tracks on one target | Sensors disagree (azimuth offset, time skew) | Fix `north_offset_deg`, sync clocks; `merge_chi2` |
| Tracks "jump" between close targets | Gate too wide in dense scenes | `gate_chi2` ↓; better sensor σ values |
| Tracks fragment when targets turn | Manoeuvre model too quiet | `imm_sigma_h_mps2` second value ↑ (8 → 10); check `imm_enabled` |
| Velocity looks jittery or overconfident | Doppler noise too low for your radar | sensor `sigma_radial_velocity_mps` ↑ (1.5 → 2–3) or `use_doppler = false` |
| Cross-range error large at long range | No second angle source | Add an EO/IR / DF bearing sensor (angular detections) |
| False tracks from clutter | Low radar threshold | `confirm_hits` ↑ (5 → 6), `max_confirm_speed_mps` ↓ |
| New tracks take too long | Slow scans × `confirm_hits` | `confirm_hits` ↓ (4, or 3) — accepts more false tracks |
| Coasting ghosts linger | `max_coast_s` too long | ↓ (e.g. 5 s) |
| Targets lost during short occlusions | `max_coast_s` too short | ↑ (12 s) |
| Display lags | Reorder window | `fusion.reorder_window_s` ↓ (0.1), `api.snapshot_hz` ↑ |
| Alert noise from birds | Class not yet decided | Send micro-Doppler dwells; lower `classifier.decision_threshold`; `alerts.suppress_class_above` |

Always tune by **replaying a recording**: `sdt-radar replay raw.jsonl --config tuned.toml` is deterministic,
so before/after comparisons are exact.

## 5. Storage, retention, backups

* **SQLite file** at `storage.path` (WAL: `-wal` and `-shm` side files are normal). Writes are batched
  every 200 ms; a clean shutdown drains the queue and archives live tracks as `lost`. A hard kill can lose
  up to ~200 ms of queued writes.
* **Growth estimate:** one point per confirmed track per second; a point row is ~300 bytes of JSON →
  100 tracks ≈ 30 KB/s ≈ 2.6 GB/day. Raise `storage.point_interval_s` to thin it (e.g. 2–5 s).
* **Retention:** set `storage.retention_days` and the service prunes hourly (points, lost tracks and closed
  alerts older than that; each run is audited). The `SqliteStore.prune()` method is still available for manual use.
* **Raw log:** `storage.recorder_path` grows without bound; rotate with `logrotate` (`copytruncate`).
* **Backup:** copy the database with `sqlite3 radar.db ".backup backup.db"` (consistent under WAL).
* **Zones** created through the API are persisted and reloaded at startup (zones in the config file are
  upserted too).

## 6. Capacity

Measured on one general-purpose core (offline data time, no network): 500 simultaneous targets ≈ 112 ms
per 2 s scan (p99 184 ms), i.e. about 5.6 % of one core. Classifying one micro-Doppler dwell costs
≈ 0.4 ms, so 100 dwells/s ≈ 4 % of a core. These are single-machine measurements: re-measure on your
hardware with `sdt-radar bench --targets N` and keep a safety margin.

## 7. Troubleshooting

| Symptom | Check |
|---|---|
| No tracks appear | `/api/v1/sensors` (detections > 0?), metrics `rejected_*`, sensor registered with the same id, `t` is current epoch seconds |
| Tracks appear in the wrong place | Azimuth convention / `north_offset_deg`, sensor coordinates, elevation sign |
| Tracks appear but never confirm | Speed > `max_confirm_speed_mps`; too few hits in `confirm_window_s`; check timestamps |
| Everything is ~seconds late | A sensor clock is ahead; compare `t` with server time |
| `serve` exits with code 2 | Non-loopback host without an API key |
| WebSocket closes with 4401 | Wrong/missing API key |
| High CPU | Many tentative tracks (clutter), huge `ws` fan-out, or tracks ≫ 500 |

## 8. Upgrade and compatibility

The API is versioned under `/api/v1` and the WebSocket carries `protocol: 1` in `hello`. Config unknown
keys are errors, so upgrade notes list renamed keys. The packaged classifier file records its feature
names and is rejected if they do not match the code.
