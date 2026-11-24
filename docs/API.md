# API reference — frontend and backend contract

Base URL (default): `http://127.0.0.1:8080` · OpenAPI UI: `/docs` · All timestamps are UNIX epoch seconds (UTC, float).
Coordinates: WGS-84 `lat`/`lon` in degrees, `alt_m` metres above the ellipsoid; local ENU metres where noted.
Course/heading: degrees clockwise from true North, 0 ≤ h < 360.

Authentication: when `api.api_key` / `SDT_RADAR_API_KEY` is set, every `/api/v1/*` request needs the header
`X-API-Key: <key>`; the WebSocket accepts the same header or `?api_key=<key>`. A wrong/missing key yields
HTTP 401 (WebSocket close code 4401). `/health` is always open and returns no sensitive data.
Examples below are illustrative values.

## 1. Track object (`TrackOut`)

```json
{
  "track_id": "c0a2bba78b6e", "seq": 1, "status": "confirmed",
  "target_class": "drone", "class_confidence": 1.0, "confidence": 0.963,
  "lat": 4.703, "lon": -74.073, "alt_m": 2698.853,
  "east_m": -65.924, "north_m": -911.266, "up_m": 98.788,
  "vel_e_mps": 0.038, "vel_n_mps": 18.932, "vel_u_mps": 0.36,
  "speed_mps": 18.935, "heading_deg": 0.115, "climb_mps": 0.36,
  "rcs_dbsm": -22.264, "position_sigma_m": 3.66,
  "sensors": ["aesa-1", "fmcw-1", "rid-1"],
  "first_seen": 1795000000.0, "last_seen": 1795000059.511, "age_s": 60.0, "hits": 228
}
```

| Field | Notes |
|---|---|
| `status` | `tentative` (hidden unless requested), `confirmed`, `coasting` (no recent hit; position extrapolated), `lost` (archive only) |
| `target_class` | `drone`, `bird`, `clutter`, or `unknown` (no/insufficient micro-Doppler evidence) |
| `class_confidence` | Posterior probability of `target_class` (0 when unknown) |
| `confidence` | Heuristic existence score 0–1; **not** a calibrated probability |
| `lat/lon/alt_m` | Live snapshots extrapolate position to "now" for up to `max_coast_s`; archived records use the last update |
| `position_sigma_m` | 1-σ position uncertainty (filter covariance) — render as an uncertainty circle |
| `sensors` | Sensors that contributed at least once |

## 2. Track history point (`TrackPoint`)

`t, lat, lon, alt_m, vel_e_mps, vel_n_mps, vel_u_mps, speed_mps, heading_deg, position_sigma_m, confidence, sensors[]`
— one point per second per confirmed track by default (`storage.point_interval_s`).

## 3. Alert object (`AlertOut`)

```json
{
  "alert_id": "9f31c0aa51de", "type": "zone_intrusion", "level": "critical", "state": "open",
  "track_id": "c0a2bba78b6e", "zone_id": "core", "zone_name": "Protected core",
  "opened_at": 1795000071.2, "updated_at": 1795000071.2, "closed_at": null,
  "risk": 1.0, "target_class": "drone",
  "message": "drone track inside 'Protected core'", "lat": 4.7112, "lon": -74.0719, "alt_m": 2701.4
}
```

`type`: `zone_intrusion` | `zone_approach` (predicted entry within `alerts.lookahead_s`, level capped at `warning`).
`state`: `open` | `closed`. `risk` ∈ [0, 1] = class weight × proximity × level weight.

## 4. REST endpoints

| Method & path | Parameters | Response |
|---|---|---|
| `GET /health` | – | `{status, version, uptime_s, tracks, sensors, ws_clients}` |
| `GET /api/v1/tracks` | `target_class`, `status`, `min_confidence` (0–1), `include_tentative` (bool), `limit` (≤ 5000) | `TrackOut[]` live |
| `GET /api/v1/tracks/{track_id}` | – | `TrackOut` (live, else archived); 404 if unknown |
| `GET /api/v1/tracks/{track_id}/history` | `since`, `until`, `limit` (≤ 20000) | `TrackPoint[]` (store; live ring-buffer fallback); 404 if unknown |
| `GET /api/v1/archive/tracks` | `status`, `target_class`, `since`, `limit` | `TrackOut[]` from the store (includes `lost`) |
| `GET /api/v1/alerts` | `active` (bool), `since`, `limit` | `AlertOut[]` (`active=true` = currently open, exact) |
| `GET /api/v1/zones` | – | `Zone[]` |
| `POST /api/v1/zones` | `Zone` body | 201 `Zone`; 422 on invalid shape; persisted |
| `DELETE /api/v1/zones/{id}` | – | 204; 404 if unknown |
| `GET /api/v1/sensors` | – | Registered sensors + `detections` count + `last_seen_age_s` |
| `POST /api/v1/sensors` | `SensorConfig` body | 201; registers at runtime |
| `POST /api/v1/ingest/detections` | JSON array (≤ 5000) of detections | `{accepted, rejected}`; 413 if too large |
| `GET /api/v1/metrics` | – | Counters, tracker stats, tracks by status, buffer, latency, step time, sensors, WebSocket stats |

### Zone body

```json
{"id": "core", "name": "Protected core", "kind": "circle",
 "center_lat": 4.711, "center_lon": -74.0721, "radius_m": 400,
 "min_alt_m": -1000, "max_alt_m": 100000, "level": "critical"}
```
Polygon: `"kind": "polygon", "polygon": [[lat, lon], [lat, lon], [lat, lon], ...]` (≥ 3 vertices).
`level`: `info` | `warning` | `critical`.

### Sensor body (`SensorConfig`)

`id, kind, lat, lon, alt_m, north_offset_deg, sigma_range_m, sigma_az_deg, sigma_el_deg, max_range_m, scan_period_s`.
`kind` ∈ `radar_fmcw`, `radar_pulse_doppler`, `radar_aesa`, `radar_passive`, `rf`, `remote_id`, `eo_ir`, `acoustic`, `other`.

### Metrics (selected)

```json
{"counters": {"received": 4040, "rejected_invalid": 0, "rejected_sensor": 0, "rejected_malformed": 0,
              "stale_measurements": 24, "classified": 584, "classifier_rejected": 0},
 "tracker": {"created": 191, "confirmed": 100, "lost": 84, "merged": 0, "stale": 0, "dropped_capacity": 0},
 "tracks_by_status": {"confirmed": 96, "coasting": 4, "tentative": 7},
 "buffer_len": 0, "buffer_dropped": 0,
 "latency_ms": {"p50": 237, "p95": 244, "p99": 249}, "step_ms": {"p50": 1.1, "p99": 15.4},
 "ws": {"clients": 2, "published": 1840, "dropped": 0}}
```

## 5. WebSocket `/ws/v1/stream`

Connect (`ws://host:8080/ws/v1/stream?api_key=…`). Server → client messages:

| `type` | Payload | When |
|---|---|---|
| `hello` | `protocol` (=1), `snapshot_hz`, `server_time` | On connect |
| `snapshot` | `server_time`, `count`, `tracks: TrackOut[]` | Every `1/snapshot_hz` s (default 5 Hz) |
| `alert` | `alert: AlertOut` | Immediately when an alert opens, escalates or closes |
| `subscribed` | `classes`, `min_confidence`, `include_tentative` | After every `subscribe` message |
| `error` | `detail` | Invalid subscribe message |

Client → server (optional, any time):

```json
{"subscribe": {"classes": ["drone"], "min_confidence": 0.5, "include_tentative": false}}
```

* Snapshots are **full state** (not deltas): render by replacing your track table; remove tracks that
  are absent. Each snapshot supersedes the previous.
* Each client has a 16-message queue; when it is full the *oldest* message is dropped (counted in
  `ws.dropped`). A slow client cannot slow the backend.
* Suggested frontend mapping: Leaflet/Cesium/Mapbox markers by `target_class`, a trail from
  `/history` (or accumulate snapshots), an uncertainty circle from `position_sigma_m`, alert panel from `alert` messages.

## 6. Ingest wire format (UDP / TCP / HTTP)

* **UDP** (port 9100): one datagram = a JSON object, a JSON array of objects, or newline-delimited JSON. ≤ 65 507 bytes.
* **TCP** (port 9101): newline-delimited JSON; a line > 1 MiB drops the connection.
* **HTTP:** `POST /api/v1/ingest/detections` with a JSON array.

Detection fields (exactly one geometry):

| Field | Type | Notes |
|---|---|---|
| `sensor_id` | string 1–64 | Must be a registered sensor |
| `t` | float | Measurement time, epoch seconds, 2000–2100 |
| `range_m`, `azimuth_deg`, `elevation_deg` | float | **Polar**: all three; azimuth clockwise from North (+ sensor `north_offset_deg`), elevation up |
| `lat`, `lon`, `alt_m` | float | **Geodetic**: all three |
| `sigma_h_m`, `sigma_v_m` | float > 0 | Geodetic position noise (defaults: sensor `sigma_range_m`, vertical ×1.5) |
| `radial_velocity_mps` | float | + receding; carried, not yet used by the filter |
| `rcs_dbsm`, `snr_db` | float | Smoothed RCS estimate is exposed on the track |
| `external_id` | string ≤ 64 | Vendor track ID / Remote ID serial |
| `md_prf_hz`, `md_iq_b64` | float, string | Micro-Doppler dwell (together): base64 of interleaved little-endian float32 I/Q, 256–16 384 complex samples |

Unknown fields, NaN/Inf, out-of-range values, both/neither geometry → rejected and counted
(`rejected_invalid`). Unknown sensors → `rejected_sensor`. Undecodable JSON → `rejected_malformed`.
