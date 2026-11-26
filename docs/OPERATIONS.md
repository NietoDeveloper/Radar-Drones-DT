# Operations guide

## 1. Deployment

| Option | Command | Notes |
|---|---|---|
| Virtualenv | `pip install . && sdt-radar serve --config /etc/sdt-radar/radar.toml` | Simplest; runs on one core of any Linux/macOS/Windows host with Python ≥ 3.11 |
| systemd | unit below | Restarts on failure, journa Too many tracks per core | Reduce load / raise gate efficiency / scale out (roadmap) |
| `tracker.dropped_capacity > 0` | `max_tracks` reached
## 4. Tuning guide

| Symptom | Likely cause | Knob |
|---|---|---|
| Tracks fragment on manoeuvres (ID switches) | Gate too tight / process noise too low | `tracker.gate_chi2` ↑ (21.1 → 25), `sigma_accel_h_mps2` ↑ |
| Two tracks on one target | Sensors disagree (azimuth offset, time skew) | Fix `north_offset_deg`, sync clocks; `merge_chi2` |
| Tracks "jump" between close targets | Gate too wide in dense scenes | `gate_chi2` ↓; better sensor σ values |
| False tracks from clutter | Low radar threshold | `confirm_hits` ↑ (5), `max_confirm_speed_mps` ↓ |
| New tracks take too long | Slow scans × `confirm_hits` | `confirm_hits` ↓ (3) — accepts more false tracks |
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
* **Retention:** `SqliteStore.prune(older_than_epoch)` deletes old points and closed/lost records;
  schedule it (cron job calling a short Python snippet) or move to TimescaleDB retention policies.
* **Raw log:** `storage.recorder_path` grows without bound; rotate with `logrotate` (`copytruncate`).
* **Backup:** copy the database with `sqlite3 radar.db ".backup backup.db"` (consistent under WAL).
* **Zones** created through the API are persisted and reloaded at startup (zones in the config file are
  upserted too).

## 6. Capacity

Measured on one general-purpose core (offline data time, no network): 500 simultaneous targets ≈ 73 ms
per 2 s scan (p99 104 ms), i.e. about 3.6 % of one core. Classifying one micro-Doppler dwell costs
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
