# Operations guide

## 1. Deployment

| Option | Command | Notes |
|---|---|---|
| Virtualenv | `pip install . && sdt-radar serve --config /etc/sdt-radar/radar.toml` | Simplest; runs on one core of any Linux/macOS/Windows host with Python ≥ 3.11 |
| systemd | unit below | Restarts on failure, journa Too many tracks per core | Reduce load / raise gate efficiencdeletes old points and closed/lost records;
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
