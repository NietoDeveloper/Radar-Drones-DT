# Architecture

## 1. Goals and non-goals

**Goals:** ingest detections from heterogeneous sensors; keep one coherent picture of every airborne
target (tracks); tell drones from birds; alert on protected zones; record everything; serve a real-time
UI with < 500 ms display latency; scale

## 2. Data flow
   alerts ◄── AlertEngine ◄── tracks ◄── MultiTargetTracker ◄──────────────────────────────┘sotropic). Geodetic: WGS-84 → ENU, diagonal covariance from
   `sigma_h_m` / `sigma_v_m`. Unknown sensors →o **its own measurement's timestamp** (rotating radars
  time-stamp plots across the scan) then updated in Joseph form (keeps `P` symmetric positive-definite).
* **Spawn:** unmatched measurements become tentative tracks (`x = z`, `P_pos = R`, `P_vel = 20² I`).
* **Lifecycle (time-based, sensor-agnostic):**

  | Transition | Rule (defaults) |
  |---|---|
  | tentative → confirmed | ≥ 4 hits within 12 s **and** speed estimate ≤ 50 m/s |
  | tentative → deleted | no hit for 4 s |
  | confirmed → coasting | no hit for 2 s |
  | coasting → confirmed | new hit gates in |
  | coasting → deleted | no hit for 8 s |
  | duplicate merge | 6-D state difference χ² < 16.8 (velocity within 10 m/s), or < 15 m / 5 m/s; older track survives |

* **Mixed-sensor batches** are split per sensor and processed in time order.
* **Stale measurements** (older than a track's state) cannot rewind a filter; they are counted.
* **Confidence** (`Track.confidence`): `(1 − 0.5^(hits−1)) × (0.4 + 0.6 × freshness)` — a monotone,
  explainable score. It is **not** a calibrated probability.

### Why GNN + Kalman (and not JPDA/MHT/IMM) in v1

GNN with a per-measurement covariance and a statistical merge handles the scenario set here (including
500 targets) at 73 ms per scan and is easy to reason about and test. The measured weak spot is
fragmentation on hard manoeuvres; IMM (constant-velocity + coordinated-turn) is the planned fix and
slots into `kalman.py` / `Track` without touching the pipeline.

## 4. Time

* **Data time vs wall time.** `Pipeline.step(now)` takes time explicitly. Live: `now = time.time()`.
  Replay/simulation: `now` is the latest data timestamp. Nothing reads the clock internally except
  latency metrics.
* **Clock sync is assumed** (NTP/PTP). A sensor whose clock runs ahead has its data held until
  `t ≤ now − 0.2 s`; one that runs behind is processed immediately but may be counted stale.
* **Latency budget (live, measured):** reorder window 200 ms + tick 50 ms ≈ 250 ms ingest→tracked
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
| Drop-oldest back-pressure everywhere | A slow consumer must never stall tracking |
| SQLite first, `Store` protocol | Zero-dependency edge deployments; clean seam for TimescaleDB |

## 8. Extension points

| To add… | Do this |
|---|---|
| A sensor | Register in config / `POST /api/v1/sensors`; emit `Detection` JSON (see SENSOR_INTEGRATION.md) |
| A classifier (CNN) | Implement `predict_proba(iq, prf_hz) -> probs[drone,bird,clutter]`, pass to `Pipeline(classifier=…)` |
| A motion model (IMM) | Extend `tracking/kalman.py` and `Track`; keep the `Measurement` input |
| A store | Implement the `Store` protocol (`docs/timescale_schema.sql` is the starting schema) |
| A new alert rule | Add a type in `models.AlertType` and a branch in `AlertEngine._eval_one` |
