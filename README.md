# sdt-drone-radar

**Python backend for radar-based drone detection — a SoftwareDT.com product.**
Version 1.0.0 · Python ≥ 3.11 · 100 % Python · FastAPI + numpy/scipy

`sdt-drone-radar` receives detections from radars and other sensors, turns them into stable **tracks**
(ID, 3-D position, velocity, heading, RCS, class, confidence, trajectory history, source sensors),
**classifies** drones versus birds from micro-Doppler signatures, raises **zone alerts**, **records**
everything, and serves it in real time through a **REST + WebSocket API** that any dashboard
(Leaflet, Cesium, Mapbox, React/Vue) or other Software DT backend can consume.

> **Scope of this repository:** the *backend* (ingestion, tracking, fusion, classification, alerting,
> recording, API) plus a simulator and test harness. The real-time map frontend is **not** in this repo;
> its contract (WebSocket protocol, data model) is fully specified in [docs/API.md](docs/API.md).
>
> **Version 1 is about architecture and a verified baseline.** It has been validated on a
> physics-based simulator, **not on real radar hardware**. See [Known limitations](#known-limitations-of-v1).

---

## Table of contents

1. [What it does](#what-it-does)
2. [Architecture at a glance](#architecture-at-a-glance)
3. [Design principles](#design-principles)
4. [Repository layout](#repository-layout)
5. [Install and run](#install-and-run)
6. [Quick start](#quick-start)
7. [Data model: what a track contains](#data-model-what-a-track-contains)
8. [API summary](#api-summary)
9. [Sensor ingestion](#sensor-ingestion)
10. [Tracking, fusion and classification](#tracking-fusion-and-classification)
11. [Alerts](#alerts)
12. [Recording and storage](#recording-and-storage)
13. [Configuration](#configuration)
14. [Requirements versus measured results](#requirements-versus-measured-results)
15. [Quality evidence](#quality-evidence)
16. [Known limitations of v1](#known-limitations-of-v1)
17. [Documentation index](#documentation-index)
18. [License](#license)

---

## What it does

| Capability | Module | Status in v1 |
|---|---|---|
| Receive detections over UDP, TCP, HTTP; strict validation of every message | `ingest/`, `models.py`, `api/` | Implemented |
| Radar polar plots (range / azimuth / elevation) and geodetic fixes (Remote ID, RF, EO/IR-derived) in one pipeline | `fusion/measurement.py` | Implemented |
| Out-of-order handling across sensors with different latencies | `fusion/reorder.py` | Implemented |
| Multi-target tracking: Kalman filter, GNN association, track lifecycle, duplicate merging | `tracking/` | Implemented |
| Multi-sensor fusion (any number of radars + position-fix sources) | `fusion/`, `tracking/` | Implemented (position-level) |
| Micro-Doppler drone/bird/clutter classification with evidence accumulated per track | `classification/` | Implemented, trained on synthetic data only |
| Protected-zone intrusion and approach alerts, risk score, bird suppression | `alerts/` | Implemented |
| Time-series + relational recording (SQLite), raw-detection audit log (JSONL), deterministic replay | `storage/`, `ingest/` | Implemented |
| REST API, WebSocket stream with per-client filters, API-key auth | `api/` | Implemented |
| Physics-based simulator, scoring against ground truth, scale benchmark | `sim/`, `bench.py` | Implemented |
| Radar range-equation sizing tool and sensor catalogue | `radar/` | Implemented |
| TimescaleDB / PostgreSQL / InfluxDB store | `docs/timescale_schema.sql` | **Schema reference only** |
| Vendor radar SDK adapters, SAPIENT bridge | `docs/SENSOR_INTEGRATION.md` | **Not included** (documented pattern) |
| CNN classifiers, passive-radar / RF / acoustic signal processing | — | Not included (plug-in point provided) |

---

## Architecture at a glance

```
 radars (FMCW · pulse-Doppler · AESA · passive) · RF · Remote ID · EO/IR · acoustic
      │ UDP / TCP / HTTP — JSON detections (vendor SDK adapters emit this format)
      ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ INGEST      strict pydantic validation · reject counters · optional raw JSONL record │
├─────────────────────────────────────────────────────────────────────────────────────┤
│ FUSION      Detection → Measurement (ENU position + 3×3 covariance, per sensor model)│
│             ReorderBuffer (0.2 s data-time window) → per-sensor time-bucket batches  │
├─────────────────────────────────────────────────────────────────────────────────────┤
│ TRACKER     predict (vectorised) → gate (Euclid + Mahalanobis²) → Hungarian GNN →   │
│             Joseph-form Kalman update → spawn / confirm / coast / delete / merge     │
├─────────────────────────────────────────────────────────────────────────────────────┤
│ CLASSIFY    micro-Doppler dwell → STFT features → logistic model → per-track evidence│
├─────────────────────────────────────────────────────────────────────────────────────┤
│ ALERTS      zones (circle / polygon + altitude band) · intrusion + approach · risk   │
└───────┬───────────────────────────┬─────────────────────────────┬───────────────────┘
        ▼                           ▼                             ▼
   STORE (SQLite WAL,         REST  /api/v1/…              WebSocket /ws/v1/stream
   writer thread)             tracks · history · alerts     snapshots @ 5 Hz + alert events
   tracks · points · alerts   zones · sensors · metrics     per-client filters, drop-oldest
        ▲                                                        │
        └──────────── any dashboard / other Software DT backend ◄┘
```

The core (`Pipeline`) is **synchronous and deterministic**: time is an explicit argument. The same code
runs live (`time.time()`), in replay and in simulation (data time) and in tests. Network, API and
WebSocket layers only wrap it. Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Design principles

1. **Everything is a measurement in one frame.** Polar radar plots and geodetic fixes both become ENU
   position + covariance, so the tracker has no sensor-specific code and heterogeneous sensors fuse naturally.
2. **Deterministic core, thin I/O shell.** Replaying the same JSONL file twice produces identical tracks
   (tested). Simulation, replay and live use the same pipeline.
3. **Strict at the edges, honest in the middle.** Every inbound message is validated; anything rejected is
   *counted and exposed* in `/api/v1/metrics`, never silently dropped.
4. **Back-pressure never blocks the tracker.** Bounded reorder buffer (sheds oldest), bounded WebSocket
   queues (drop oldest), disk writes on a dedicated thread.
5. **Uncertainty is first-class.** Every measurement carries a covariance; every track exposes
   `position_sigma_m` and a heuristic `confidence`; classification keeps running evidence, not a single guess.
6. **Reduce false alarms before alerting.** Track confirmation (M hits + kinematic plausibility), micro-Doppler
   classification, and bird suppression sit in front of the alert engine.
7. **Pluggable edges.** `Store`, `Classifier`, sensor adapters and the transport are small interfaces.
8. **Safe by default.** Binds to loopback; the CLI refuses to expose the API on another interface without an API key.

---

## Repository layout

```
sdt-drone-radar/
├── pyproject.toml · Dockerfile · README.md
├── config/default.toml            fully commented example configuration
├── docs/
│   ├── ARCHITECTURE.md            pipeline, threading, time handling, design decisions
│   ├── RADAR_PRIMER.md            radar types, bands, ranges, requirements → how the repo addresses each
│   ├── API.md                     REST, WebSocket, ingest wire format, data model (frontend contract)
│   ├── SENSOR_INTEGRATION.md      writing adapters for real radars / RF / Remote ID; time sync; frames
│   ├── CLASSIFICATION.md          micro-Doppler physics, features, model, limits, how to swap in a CNN
│   ├── OPERATIONS.md              deployment, security, monitoring, retention, tuning
│   ├── ROADMAP.md                 v1 → v2 → v3
│   └── timescale_schema.sql       reference schema for a TimescaleDB deployment (untested)
├── src/sdt_radar/
│   ├── models.py  config.py  geo.py  pipeline.py  runtime.py  cli.py  bench.py
│   ├── ingest/          UDP + TCP servers, JSONL recorder, replay
│   ├── fusion/          Detection→Measurement, reorder buffer, batching
│   ├── tracking/        Kalman primitives, Track, MultiTargetTracker
│   ├── classification/  micro-Doppler synthesis + features, logistic model, packaged model
│   ├── alerts/          zones, intrusion / approach engine, risk score
│   ├── storage/         Store protocol, MemoryStore, SqliteStore
│   ├── api/             FastAPI app, WebSocket hub
│   ├── radar/           range equation, sensor catalogue
│   └── sim/             targets, sensor models, scenarios, scoring
├── tests/               58 tests (unit, scenario, API, WebSocket, UDP/TCP, CLI)
└── .github/workflows/ci.yml
```

---

## Install and run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"            # runtime deps: numpy, scipy, pydantic, fastapi, uvicorn
pytest -q                          # 58 tests, ~40 s
ruff check src tests && mypy src   # both clean
```

Run the service (loopback by default):

```bash
sdt-radar serve --config config/default.toml
# UDP ingest :9100   TCP ingest :9101   API + WebSocket :8080   (docs at /docs)
```

To expose the API beyond loopback, an API key is **mandatory** (the command refuses otherwise):

```bash
SDT_RADAR_API_KEY='change-me' sdt-radar serve --config config/default.toml --host 0.0.0.0
```

Docker (provided, not built in the authoring environment): `docker build -t sdt-drone-radar .`

---

## Quick start

### 1. Watch a simulated perimeter attack (two terminals)

```bash
# terminal 1
SDT_RADAR_API_KEY=demo sdt-radar serve --config config/default.toml

# terminal 2: registers the scenario's sensors + zone, then streams detections over UDP in real time
sdt-radar sim --scenario perimeter --seed 1 --duration 60 \
              --udp 127.0.0.1:9100 --api http://127.0.0.1:8080 --api-key demo
```

The scenario has 6 drones (half heading for the protected zone) and 15 birds, seen by an FMCW radar,
an AESA panel and a Remote ID receiver.

```bash
curl -s -H 'x-api-key: demo' 'localhost:8080/api/v1/tracks?target_class=drone' | python -m json.tool | head -40
curl -s -H 'x-api-key: demo' 'localhost:8080/api/v1/alerts?active=true'
curl -s -H 'x-api-key: demo' 'localhost:8080/api/v1/metrics'
```

### 2. Subscribe to the live stream

```python
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://127.0.0.1:8080/ws/v1/stream?api_key=demo") as ws:
        await ws.send(json.dumps({"subscribe": {"classes": ["drone"], "min_confidence": 0.5}}))
        async for raw in ws:
            msg = json.loads(raw)
            if msg["type"] == "snapshot":
                print(len(msg["tracks"]), "drone tracks")
            elif msg["type"] == "alert":
                print("ALERT", msg["alert"]["level"], msg["alert"]["message"])

asyncio.run(main())
```

### 3. Offline: score, replay, benchmark, size a radar

```bash
sdt-radar score --scenario perimeter --seed 1         # tracking metrics against ground truth
sdt-radar sim --scenario perimeter --out raw.jsonl    # write a detection log
sdt-radar replay raw.jsonl --config config/default.toml
sdt-radar bench --targets 500                         # 500 simultaneous tracks
sdt-radar budget --power-w 10 --gain-dbi 35 --freq-ghz 10 --bandwidth-mhz 5 --integration-db 30
#   → max detection range (0.01 m² at SNR>=13.0 dB): 3,457 m
sdt-radar catalog                                     # sensor-type reference
```

---

## Data model: what a track contains

Every track returned by the REST API and WebSocket (`TrackOut`):

| Field | Meaning |
|---|---|
| `track_id`, `seq` | Unique ID (random 12-hex) and a per-run sequence number for display |
| `status` | `tentative` → `confirmed` → `coasting` (→ `lost` in the archive) |
| `lat`, `lon`, `alt_m` | WGS-84 position (altitude above the ellipsoid) |
| `east_m`, `north_m`, `up_m` | Position in the site's local ENU frame |
| `vel_e/n/u_mps`, `speed_mps`, `heading_deg`, `climb_mps` | Velocity, course over ground (0° = North, clockwise), climb rate |
| `target_class`, `class_confidence` | `drone` / `bird` / `clutter` / `unknown` and posterior probability |
| `confidence` | Heuristic existence score 0–1 (support, freshness) — **not** a calibrated probability |
| `rcs_dbsm` | Smoothed radar cross-section estimate |
| `position_sigma_m` | 1-σ position uncertainty from the filter covariance |
| `sensors` | Which sensors contributed (e.g. `["aesa-1","fmcw-1","rid-1"]`) |
| `first_seen`, `last_seen`, `age_s`, `hits` | Lifetime and number of supporting measurements |

Trajectory history (`/tracks/{id}/history`): `t, lat, lon, alt_m, velocity, speed, heading, position_sigma_m,
confidence, sensors` — one point per second by default, stored for confirmed tracks only.

---

## API summary

Full reference with examples: [docs/API.md](docs/API.md). Interactive OpenAPI at `/docs`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness (unauthenticated, no sensitive data) |
| GET | `/api/v1/tracks` | Live tracks; filters `target_class`, `status`, `min_confidence`, `include_tentative`, `limit` |
| GET | `/api/v1/tracks/{id}` | One track (live, else archived) |
| GET | `/api/v1/tracks/{id}/history` | Stored trajectory (`since`, `until`, `limit`) |
| GET | `/api/v1/archive/tracks` | Historical tracks from the store |
| GET | `/api/v1/alerts` | Alerts (`active=true` for open ones) |
| GET/POST/DELETE | `/api/v1/zones` | Manage protected zones at runtime (persisted) |
| GET/POST | `/api/v1/sensors` | Sensor registry and health |
| POST | `/api/v1/ingest/detections` | HTTP ingestion of up to 5 000 detections |
| GET | `/api/v1/metrics` | Counters, tracker stats, latency, step time, WebSocket stats |
| WS | `/ws/v1/stream` | `hello`, `snapshot` (5 Hz), `alert`, `subscribed`, `error` |

Auth: `X-API-Key` header (or `?api_key=` on the WebSocket) when an API key is configured.

---

## Sensor ingestion

One JSON shape for every sensor, over UDP (object, array, or newline-delimited), TCP (newline-delimited)
or HTTP. A radar plot:

```json
{"sensor_id": "fmcw-1", "t": 1795000012.37, "range_m": 1843.2, "azimuth_deg": 211.4, "elevation_deg": 6.1,
 "radial_velocity_mps": -9.8, "rcs_dbsm": -21.5, "snr_db": 17.2}
```

A Remote ID / RF / EO-IR position fix (geodetic):

```json
{"sensor_id": "rid-1", "t": 1795000012.0, "lat": 4.7132, "lon": -74.0698, "alt_m": 2701.0,
 "sigma_h_m": 4.0, "sigma_v_m": 6.0, "external_id": "1581F00000000"}
```

Optional micro-Doppler dwell for classification: `md_prf_hz` + `md_iq_b64` (base64 of interleaved
little-endian float32 I/Q slow-time samples, ≥ 256 samples). Sensors must be **registered** (config file
or `POST /api/v1/sensors`) so the backend knows their position, azimuth reference and noise model.
Vendor SDK / protocol adapters (SAPIENT, ASTERIX, proprietary) are small processes that emit this
format — see [docs/SENSOR_INTEGRATION.md](docs/SENSOR_INTEGRATION.md).

---

## Tracking, fusion and classification

* **Filter:** 3-D constant-velocity Kalman filter (state `[x y z vx vy vz]`), white-noise-acceleration
  process model with separate horizontal (4 m/s²) and vertical (2.5 m/s²) intensities, Joseph-form update.
* **Association:** vectorised prediction of all tracks; coarse Euclidean gate, then exact Mahalanobis²
  (track innovation covariance **+ the measurement's own covariance**); Hungarian assignment with
  confirmed/coasting tracks served before tentative ones. Gate: χ² 21.1 (3 dof, 99.99 %).
* **Lifecycle:** spawn tentative → **confirm after 4 hits within 12 s and speed ≤ 50 m/s** → coast after
  2 s of silence → delete after 8 s; tentatives die after 4 s; statistically identical tracks are merged
  (χ² on the 6-D state difference); capacity limit (2 000 tracks).
* **Multi-sensor:** each sensor batch is associated separately in time order, so two sensors can never
  "see the same target twice" in one pass; each update uses that sensor's own covariance.
* **Classification:** a short coherent dwell → STFT features (bandwidth, spectral flatness, temporal
  stationarity, harmonic-comb strength…) → multinomial logistic regression → per-track posterior with
  exponential forgetting. A track is labelled only when the posterior reaches 0.7; otherwise `unknown`.

Why these choices and their limits: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/CLASSIFICATION.md](docs/CLASSIFICATION.md).

---

## Alerts

* **`zone_intrusion`** — a live track is inside a zone (circle or polygon, plus altitude band).
* **`zone_approach`** — straight-line extrapolation enters a zone within 30 s (level capped at `warning`).
* One open alert per (track, zone, type); escalates when class or risk changes; closes after 5 s without
  the condition or when the track is lost (hysteresis, no alert storms).
* **Risk** = class weight (drone 1.0, unknown 0.6, bird 0.15, clutter 0.05) × proximity × zone level
  weight — transparent, tunable, in `alerts/engine.py`.
* Birds/clutter classified with ≥ 0.9 confidence raise **no** alert; `unknown` is never suppressed.

---

## Recording and storage

* **SQLite (WAL)** with a dedicated writer thread (batched commits every 200 ms; `close()` drains the queue):
  `tracks` (metadata), `points` (time series, indexed by track and time), `alerts`, `zones`.
  Only **confirmed** tracks are stored, so false tentatives never pollute history.
  Tracks live at shutdown are archived as `lost`.
* **Raw detections:** `storage.recorder_path` appends every accepted detection as JSON lines — an audit
  trail and the input for `sdt-radar replay`.
* **Retention:** `SqliteStore.prune(older_than)`; see [docs/OPERATIONS.md](docs/OPERATIONS.md).
* **TimescaleDB / PostgreSQL:** the `Store` protocol is the integration point; a reference schema with
  hypertable, compression and retention is in `docs/timescale_schema.sql` (not yet implemented or tested).

---

## Configuration

One typed, validated TOML file (unknown keys are errors); every key has a default.
See the commented [config/default.toml](config/default.toml). Secrets via environment:
`SDT_RADAR_API_KEY`. Sections: `site`, `ingest`, `fusion`, `tracker`, `classifier`, `alerts`, `storage`,
`api`, `[[sensors]]`, `[[zones]]`.

---

## Requirements versus measured results

The brief set these targets. "Measured" is from this repository's simulator — **evidence the software
meets them, not proof about any radar.** Whether a *sensor* detects a 0.01 m² target at 2–5 km is a
radar-hardware property (use `sdt-radar budget` and a vendor datasheet).

| Requirement | Measured here |
|---|---|
| Probability of detection ≥ 90 % | Track-level detection rate **≥ 98.6 %** on every one of 8 seeds in the perimeter scenario; **98.5 %** with 500 targets. Sensor Pd is a simulator input (Swerling-I, 0.9 at the configured R90). |
| Low false alarms | **0.9** never-matched (false) confirmed tracks per 150 s on average (worst 3) with ~2.5 clutter plots per scan; 0 in the 500-target run |
| Update rate ≤ 1–3 s | Radar scan periods 0.5–2 s are inputs; the pipeline processes a scan in **~1 ms** (perimeter) and **73 ms** (500 targets) |
| ≥ 100–500 simultaneous tracks | **500 targets** tracked (~500 live tracks); step time p50 **73 ms**, p99 **104 ms** per 2 s scan (~250 detections); ≈ 6× faster than real time on one core |
| Display latency < 500 ms | Ingest → tracked **p50 237 ms, p99 249 ms** in a live UDP run (dominated by the 0.2 s reorder window + 50 ms tick); WebSocket snapshots every 200 ms |
| Drone vs bird discrimination | Single-dwell accuracy 91 % (drone recall 97 %, bird 94 %, clutter 81 %); **0 drone↔bird confusions** at track level in 8 seeds — *on synthetic signatures from the same generator* |
| Position accuracy | Perimeter (FMCW + AESA + Remote ID): **RMSE ≈ 10 m horizontal, ≈ 13 m vertical**; long-range pulse-Doppler swarm: ≈ 35 m (the sensor's cross-range noise at 7 km) |
| Track continuity | 4.8 ID switches per 150 s over 21 targets on average (worst 9) |

---

## Quality evidence

* **58 automated tests, 0 failures** (~40 s): geodesy and polar conventions, model validation, Kalman
  consistency (NIS), batch/scalar predict equivalence, multi-target tracking, confirmation / coasting /
  deletion / re-acquisition, stale-measurement handling, capacity limit, two-sensor fusion accuracy gain,
  duplicate merging, reorder buffer, micro-Doppler features and held-out classifier accuracy, alert
  hysteresis / approach / suppression / polygon & altitude containment, both storage backends and
  restart durability, deterministic replay, radar-equation scaling laws, Swerling Pd behaviour,
  scenario-level requirements, 200-target scale, REST + WebSocket + auth, UDP/TCP ingest with latency
  budget, CLI and configuration validation.
* `ruff check` and `mypy` (pydantic plugin) pass on the whole source tree.
* Verified live: `serve` + `sim --udp` over real sockets, 21 tracks classified 6 drones / 15 birds,
  3 sensors fused, state persisted in SQLite (tracks, 598 points, alerts, zones).

---

## Known limitations of v1

Stated plainly so nobody mistakes a verified baseline for a fielded system:

* **Validated on a simulator only.** No real radar, no real RF/Remote ID receiver was used. The sensor
  models are planning-grade (Swerling-I detection, range-scaled noise), not waveform-level.
* **The classifier is trained on synthetic micro-Doppler** (X-band, PRF 10–16 kHz). Real birds, drones,
  rain and multipath will differ; it must be retrained/validated on recorded data per radar band.
  Clutter is the weakest class (81 % single-dwell recall; mostly confused with birds).
* **No vendor adapters, no SAPIENT/ASTERIX bridge, no passive-radar / RF / acoustic signal processing.**
  Those sensors enter as position fixes.
* **Single motion model** (constant velocity). Radial velocity is carried but not yet used in the filter;
  hard-maneuvering targets can fragment tracks (see ID-switch numbers). IMM is on the roadmap.
* **Bearing-only sensors** (EO/IR, acoustic arrays) are not fused natively; supply position fixes.
* **Storage:** SQLite only; TimescaleDB/PostgreSQL/InfluxDB/Redis are design references, not code.
* **Security:** API key + loopback default; no TLS, user accounts or rate limiting — put it behind a
  reverse proxy / VPN. The UDP ingest is unauthenticated by design (restrict at the network layer).
* **Time:** sensors must be clock-synchronised (NTP/PTP). Detections stamped in the future wait in the
  reorder buffer; very late ones are counted as stale.
* **Single process**, one core of tracking; the 500-target benchmark leaves ample headroom but there is
  no horizontal scaling yet.
* **The frontend is not included.**
* The Docker image and CI workflow are provided but were not executed in the authoring environment.

The prioritised fix list is in [docs/ROADMAP.md](docs/ROADMAP.md).

---

## Documentation index

| Document | Read it to learn… |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Pipeline internals, time handling, threading, design decisions |
| [docs/RADAR_PRIMER.md](docs/RADAR_PRIMER.md) | Which radars suit drone detection, bands, ranges, requirements, and how this repo maps to them |
| [docs/API.md](docs/API.md) | Exact REST / WebSocket / ingest contract for frontends and other backends |
| [docs/SENSOR_INTEGRATION.md](docs/SENSOR_INTEGRATION.md) | Connecting real hardware and vendor SDKs |
| [docs/CLASSIFICATION.md](docs/CLASSIFICATION.md) | Micro-Doppler physics, features, model, retraining, swapping in a CNN |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Deploying, securing, monitoring, tuning |
| [docs/ROADMAP.md](docs/ROADMAP.md) | What comes after v1 |

---

## License

Proprietary — © SoftwareDT.com. All rights reserved. (Replace if the project is later open-sourced.)
