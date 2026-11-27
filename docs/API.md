# API reference — frontend and backend contract

Base URL (default): `http://127.0.0.1:8080` · OpenAPI UI: `/docs` · All timestamps are UNIX epoch seconds (UTC, float).
Coordinates: WGS-84 `lat`/`lon` in degrees, `alt_m` metres above the ellipsoid; local ENU metres where noted.
Course/heading: degrees clockwise from true North, 0 ≤ h < 360.

**Authentication (v2).** When keys are configured (`[[api.keys]]` or the legacy `SDT_RADAR_API_KEY`) every
`/api/v1/*` and `/metrics` request needs `X-API-Key: sdtr_<id>_<secret>`. Roles are hierarchical:
**viewer < operator < admin** (the "Role" column below is the *minimum* role). Responses:

| Status | Meaning |
|---|---|
| 401 | missing / invalid key |
| 403 | valid key, insufficient role |
| 429 | per-IP rate limit, or temporary lockout after repeated failures (`Retry-After` header) |
| 413 | request body larger than `api.max_body_bytes` |

Browsers: do **not** put the key in a WebSocket URL — request a one-time ticket (see §5). `/health` is open and
returns no sensitive data. Every response carries `X-Request-ID` (send your own, 8–64 chars `[A-Za-z0-9-]`, to
correlate logs) and hardening headers. See [SECURITY.md](SECURITY.md). Examples below are illustrative values.

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

| Method & path | Role | Parameters | Response |
|---|---|---|---|
| `GET /health` | none | – | `{status, version, uptime_s, tracks, sensors, ws_clients}` |
| `GET /metrics` | viewer (or none if `metrics_public`) | – | Prometheus text exposition (see OPERATIONS.md) |
| `GET /api/v1/auth/whoami` | viewer | – | `{key_id, role}` |
| `POST /api/v1/auth/ws-ticket` | viewer | – | `{ticket, expires_in_s}` — single use |
| `GET /api/v1/audit` | admin | `limit` (≤ 1000) | last audit records (hash-chained) |
| `GET /api/v1/audit/head` | admin | – | `{seq, hash}` of the newest record — anchor it externally |
| `GET /api/v1/tracks` | viewer | `target_class`, `status`, `min_confidence` (0–1), `include_tentative` (bool), `limit` (≤ 5000) | `TrackOut[]` live |
| `GET /api/v1/tracks/{track_id}` | viewer | – | `TrackOut` (live, else archived); 404 if unknown |
| `GET /api/v1/tracks/{track_id}/history` | viewer | `since`, `until`, `limit` (≤ 20000) | `TrackPoint[]` (store; live ring-buffer fallback); 404 if unknown |
| `GET /api/v1/archive/tracks` | viewer | `status`, `target_class`, `since`, `limit` | `TrackOut[]` from the store (includes `lost`) |
| `GET /api/v1/alerts` | viewer | `active` (bool), `since`, `limit` | `AlertOut[]` (`active=true` = currently open, exact) |
| `GET /api/v1/zones` | viewer | – | `Zone[]` |
| `POST /api/v1/zones` | operator | `Zone` body | 201 `Zone`; 422 on invalid shape; persisted |
| `DELETE /api/v1/zones/{id}` | operator | – | 204; 404 if unknown |
| `GET /api/v1/sensors` | viewer | – | Registered sensors + `detections` count + `last_seen_age_s` |
| `POST /api/v1/sensors` | admin | `SensorConfig` body | 201; registers at runtime |
| `POST /api/v1/ingest/detections` | operator | JSON array (≤ 5000) of detections | `{accepted, rejected}`; 413 if too large |
| `GET /api/v1/metrics` | viewer | – | Counters, tracker stats, tracks by status, buffer, latency, step time, sensors, WebSocket stats |

### Zone body

```json
{"id": "core", "name": "Protected core", "kind": "circle",
 "center_lat": 4.711, "center_lon": -74.0721, "radius_m": 400,
 "min_alt_m": -1000, "max_alt_m": 100000, "level": "critical"}
```
Polygon: `"kind": "polygon", "polygon": [[lat, lon], [lat, lon], [lat, lon], ...]` (≥ 3 vertices).
`level`: `info` | `warning` | `critical`.

### Sensor body (`SensorConfig`)

`id, kind, lat, lon, alt_m, north_offset_deg, sigma_range_m, sigma_az_deg, sigma_el_deg,
sigma_radial_velocity_mps (default 1.5; null disables Doppler), max_range_m, scan_period_s, rate_limit_per_s,
hmac_secret_env, hmac_secret_file`. The two secret *locations* are accepted on registration but never returned;
`GET /api/v1/sensors` reports `signed: true|false` instead. Registering a sensor whose secret cannot be loaded
returns 422 (fail closed).
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

**Browser flow (recommended):** `POST /api/v1/auth/ws-ticket` with your key in the header → connect to
`wss://host:8080/ws/v1/stream?ticket=<ticket>`. A ticket is random, valid `ws_ticket_ttl_s` (30 s) and
**single-use**. Non-browser clients may send `X-API-Key` on the handshake instead. `?api_key=` is refused unless
`api.allow_query_api_key = true` (keys in URLs leak into proxy/access logs). Close codes: 4401 unauthenticated,
4429 rate-limited/locked. Server → client messages:

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
| `azimuth_deg`, `elevation_deg` (no `range_m`) | float | **Angular / bearing-only** (EO/IR, acoustic, RF direction finder). Refines existing confirmed tracks; cannot start one |
| `lat`, `lon`, `alt_m` | float | **Geodetic**: all three |
| `sigma_h_m`, `sigma_v_m` | float > 0 | Geodetic position noise (defaults: sensor `sigma_range_m`, vertical ×1.5) |
| `radial_velocity_mps` | float | + receding; used for **Doppler-aided updates** (gated; noise = sensor `sigma_radial_velocity_mps`) |
| `sig` | 64 hex chars | HMAC-SHA256 of the canonical JSON of the detection without `sig`; **mandatory** for sensors with a secret (or all, if `ingest.require_signatures`). See SECURITY.md §3 |
| `rcs_dbsm`, `snr_db` | float | Smoothed RCS estimate is exposed on the track |
| `external_id` | string ≤ 64 | Vendor track ID / Remote ID serial |
| `md_prf_hz`, `md_iq_b64` | float, string | Micro-Doppler dwell (together): base64 of interleaved little-endian float32 I/Q, 256–16 384 complex samples |

Rejections are counted and exposed in `/api/v1/metrics` and `/metrics`:

| Counter | Cause |
|---|---|
| `rejected_invalid` | schema violation: unknown field, NaN/Inf, out of range, wrong/missing geometry, not JSON |
| `rejected_malformed` | undecodable line / datagram |
| `rejected_sensor` | unregistered sensor, unusable micro-Doppler payload |
| `rejected_rate` | per-sensor rate limit exceeded (network path) |
| `rejected_unsigned` / `rejected_bad_signature` | signature missing / wrong (audited) |
| `rejected_skew` | signed timestamp outside `ingest.max_clock_skew_s` |
| `rejected_replay` | a signature that was already used (audited) |
