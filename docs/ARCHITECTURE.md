# Architecture

## 1. Goals and non-goals

**Goals:** ingest detections from heterogeneous sensors; keep one coherent picture of every airborne
target (tracks); tell drones from birds; alert on protected zones; record everything; serve a real-time
UI with < 500 ms display latency; scale

## 2. Data flow
   alerts ◄── AlertEngine ◄── tracks ◄── MultiTargetTracker ◄──────────────────────────────┘sotropic). Geodetic: 

  (p50 237 ms, p99 249 ms), + ≤ 200 ms until the next WebSocket snapshot ≈ 450 ms worst case.
  Lowering `fusion.reorder_window_s` trades latency for ordering robustness.

## 5. Concurrency model

| Context | Does | Shares with others |
|---|---|---|
| asyncio event loop (main) | UDP/TCP servers, 50 ms pipeline tick, WebSocket hub, REST handlers | `Pipeline` guarded by an `RLock` |
| SQLite writer thread | Batches queue → `executemany` → commit every 200 ms | `SimpleQueue` only |
| Reader connection | REST history/archive queries (`asyncio.to_thread`) | WAL permits concurrent read |

Tracking, classification and alerting run on the event loop: at 500 tracks a step costs ~73 ms every
2 s (≈ 3.6 % of one core). If scale demands it, the `Pipeline` can move to its own process behind a queue
without API changes because it is already synchronous and self-contained.

Back-pressure: reorder buffer (`ingest.queue_size`, default 50 000 items, sheds oldest) · WebSocket queue per client (16 messages,
drops oldest) · store queue (unbounded but drained continuously; `errors` counter on SQL failures).

## 6. Module map

| Module | Responsibility |
|---|---|
| `models.py` | Enums, `Detection` (wire), `Measurement`, `ClassPosterior`, API output models, `Zone`, `SensorConfig` |
| `geo.py` | WGS-84 ↔ ENU, polar ↔ ENU with covariance |
| `config.py` | Typed settings + TOML loader + env override |
| `fusion/` | Conversion, reorder buffer, batching |
| `tracking/` | Kalman math, `Track`, `MultiTargetTracker` |
| `classification/` | Signal synthesis, features, logistic model, training |
| `alerts/` | Zone geometry, alert state machine, risk |
| `storage/` | `Store` protocol + memory + SQLite |
| `pipeline.py` | Orchestrator (deterministic) |
| `runtime.py` | Async tick, servers, hub |
| `api/` | FastAPI app + WebSocket hub |
| `sim/` | Targets, sensor models, scenarios, scoring |
| `radar/` | Radar equation + catalogue |

## 7. Key decisions

| Decision | Reason |
|---|---|
| ENU + covariance as the only tracker input | One tracker for radar, Remote ID, RF, EO/IR-derived fixes |
| Deterministic synchronous core | Replay, simulation, tests and live share code; bit-identical replays |
| Covariance per measurement | A 4 m Remote ID fix and a 70 m cross-range radar plot are weighted correctly |
| Track-time update (not batch-time) | Rotating radars stamp plots across the scan; avoids 10–20 m time-skew errors |
| Confirm only plausible tracks | Cut never-matched false tracks ≈ 8× in a 6-seed comparison (1.33 → 0.17 per 150 s going from 3 to 4 hits) |
| Wider gate (χ² 21.1) | Cut ID switches 16.8 → 5 in a parameter sweep; larger gates cost association ambiguity in dense scenes (500-target run stays at 98.5 % detection) |
| Store only confirmed tracks | History is evidence, not noise |
