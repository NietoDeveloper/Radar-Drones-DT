# Architecture (v2)

## 1. Goals and non-goals

**Goals:** ingest detections from heterogeneous sensors; keep one coherent picture of every airborne
target (tracks); tell drones from birds; alert on protected zones; record everything; serve a real-time UI
with < 500 ms display latency; scale to hundreds of simultaneous tracks; resist spoofing, flooding and
unauthorised access; be testable without hardware.

**Non-goals:** radar signal processing (range-Doppler, CFAR — the radar/SDK does that and emits plots), the
frontend, effectors/countermeasures, vendor-specific drivers.

## 2. Data flow

```
sensor ─► [edge forwarder: sign · batch · HTTPS] ─┐
sensor ─► UDP / TCP / HTTP ───────────────────────┤
                                                  ▼
   INGEST GUARD  parse → rate limit → signature → skew → replay → schema          (security/, pipeline.ingest_raw)
        │
        ▼
   Detection (wire) ─► Measurement (ENU + covariance; polar | angular | geodetic) ─► ReorderBuffer ─► batches
                                                                                              │
   alerts ◄── AlertEngine ◄── tracks ◄── MultiTargetTracker (IMM · Doppler · bearing-only) ◄──┘
      │            ▲              │ ▲
      │            │              │ └── classifier posterior per track (micro-Doppler dwell)
      ▼            │              ▼
  Store · WS · webhooks     Store · REST · WS · /metrics
```

### Stage by stage

1. **Ingest guard (`Pipeline.ingest_raw`).** Untrusted input only. Order (cheapest and most
   security-relevant first): parse → per-sensor token bucket → HMAC signature (sensors with a secret, or all
   when `require_signatures`) → timestamp within the clock-skew window → replay cache → schema validation.
   Every rejection has its own counter; signature failures and replays are written to the audit log.
   In-process callers (`Pipeline.ingest`, simulator, replay) are trusted and skip the guard.
2. **Validation (`models.Detection`).** Exactly one geometry: *polar* (range/azimuth/elevation),
   *angular* (azimuth/elevation only — EO/IR, acoustic and RF direction finders) or *geodetic*
   (lat/lon/alt). Finite numbers, ranges, plausible time, no unknown fields.
3. **Conversion (`fusion/measurement.py`).**
   * Polar: sensor ENU position + `polar_to_enu`, covariance from a Jacobian of σ_range/σ_az/σ_el
     (grows with range, anisotropic); keeps the sensor position and, if present, the radial velocity with
     its noise for Doppler-aided updates.
   * Angular: `z = [azimuth, elevation]` in radians, `R = diag(σ_az², σ_el²)`, plus sensor position.
   * Geodetic: WGS-84 → ENU, diagonal covariance from `sigma_h_m` / `sigma_v_m`.
4. **Re-ordering (`fusion/reorder.py`).** Heap by measurement time; release everything older than
   `now − 0.2 s`; overflow sheds the *oldest* data (`buffer_dropped`). Released data is batched per
   `(sensor, time bucket 0.25 s)`.
5. **Tracking (`tracking/`).** §3.
6. **Classification.** Each matched measurement carrying a micro-Doppler dwell updates the track's
   `ClassPosterior`.
7. **Alerting.** Evaluated at most every 0.5 s over live tracks; events go to the store, the WebSocket
   hub and the (optional) signed webhooks.
8. **Persistence.** Confirmed tracks write metadata + one point per `point_interval_s`; optional hourly
   retention pruning.
9. **Publication.** REST reads live state; WebSocket snapshots at 5 Hz; Prometheus at `/metrics`.

## 3. The tracker

State `x = [x y z vx vy vz]` (ENU, metres, m/s) with covariance `P`, held **per motion model** by an IMM
and exposed as the moment-matched fusion.

### 3.1 Interacting Multiple Model (`tracking/imm.py`)

Two constant-velocity models differ only in manoeuvre noise: *quiet* (σ_a = 1.5 m/s² horizontal, 1.0
vertical) and *manoeuvre* (8.0 / 4.0). Each cycle: **mix** the model states by their transition
probabilities → **predict** each model → **update** each with the measurement → re-weight by the measurement
likelihood → **combine**. A single process-noise setting forces a trade-off (tight gates lose turning
targets, loose ones add noise); the IMM gets both.

* Switching probability is defined **per second** and scaled exactly: `T(dt) = U + λ^dt (I − U)`,
  `λ = (M·stay − 1)/(M − 1)`. A target updated by three sensors per second is not "switched" three times as
  often, and `dt = 0` means no transition (tested).
* One vectorised implementation serves association (all N tracks) and update (N = 1).
* `imm_enabled = false` falls back to a single model (σ = `sigma_accel_*`).

### 3.2 Measurements (`tracking/meas.py`)

Each sensor physics is one linearisation `(state) → (innovation y, Jacobian H, noise R)`:

| Measurement | Used for | Notes |
|---|---|---|
| `pos_lin` | polar plots, Remote ID, RF/EO fixes | linear; per-measurement covariance |
| `dop_lin` | radar radial velocity (range-rate) | scalar EKF update after the position update; **gated** (χ² 9) so aliased / spoofed Doppler is ignored |
| `ang_lin` | EO/IR, acoustic, RF direction finders | az/el EKF update with wrapped azimuth innovation; Jacobians verified against finite differences |

Doppler noise defaults to 1.5 m/s (sensor `sigma_radial_velocity_mps`). The *measured* noise is ~0.3 m/s,
but using it made tracks overconfident in velocity: ID switches rose from 4 to 24 per run in the ablation.
1.5 m/s absorbs target acceleration over the dwell and rotating-radar time skew.

### 3.3 Association

* Predict all tracks together to the batch reference time (`einsum`).
* Position batches: Euclidean coarse gate, then exact `d² = yᵀ(P_pos + R_meas)⁻¹y` (batched solve); accept
  `d² < 21.1`; Hungarian assignment in two stages (confirmed/coasting first, then tentative).
* **Bearing-only batches:** gate in angle space (`d²` with the 2×2 predicted angular covariance + R, closed
  form, χ² 13.8), Hungarian assignment; matched bearings update the track through the EKF.
  * They **refine only `confirmed` tracks** and **never** change existence evidence (`hits`,
    `last_hit_t`, status). A line of sight crosses many clutter points (it would confirm false tracks), and
    it cannot fix range (it would keep a ghost alive on the wrong point of the ray). Unmatched bearings are
    counted (`angular_unmatched`); a bearing can never *start* a track.
* Each matched track is propagated to **its own measurement's timestamp** (rotating radars time-stamp plots
  across the scan) before the update.
* Mixed-sensor or mixed-geometry batches are split and processed per `(sensor, geometry)` in time order.

### 3.4 Lifecycle

| Transition | Rule (defaults) |
|---|---|
| tentative → confirmed | ≥ **5** hits within 12 s **and** speed estimate ≤ 50 m/s |
| tentative → deleted | no hit for 4 s |
| confirmed → coasting | no hit for 2 s |
| coasting → confirmed | a position hit gates in |
| coasting / confirmed → deleted | no hit for 8 s, **or** speed estimate > 70 m/s (kinematically impossible) |
| duplicate merge | 6-D χ² of the state difference < 16.8, or < 15 m & 5 m/s; older track survives |

The 6-D χ² weighs the velocity difference by both tracks' velocity uncertainty: a poorly known duplicate
(huge velocity variance) merges into the established track; two well-known crossing targets do not.
`Track.confidence` = `(1 − 0.5^(hits−1)) × (0.4 + 0.6 × freshness)` — a monotone, explainable score, **not** a
calibrated probability.

## 4. Time

* `Pipeline.step(now)` takes time explicitly. Live: `time.time()`; replay/simulation: latest data time.
* **Clock sync is assumed** (NTP/PTP) — and, for signed sensors, enforced by the skew window.
* **Latency budget (live, measured):** reorder window 200 ms + tick 50 ms ≈ 250 ms ingest→tracked
  (p50 237 ms, p99 249 ms) + ≤ 200 ms to the next WebSocket snapshot ≈ 450 ms worst case.

## 5. Concurrency

| Context | Does | Shares |
|---|---|---|
| asyncio loop | UDP/TCP servers, 50 ms pipeline tick, WebSocket hub, REST, retention task | `Pipeline` guarded by an `RLock` |
| SQLite writer thread | queue → `executemany` → commit every 200 ms | `SimpleQueue` |
| Webhook thread | bounded queue → signed POST with retry/back-off | queue only |
| Forwarder thread (edge) | bounded deque → batched HTTPS POST | deque + condition |

Back-pressure everywhere sheds the **oldest** data and counts it: reorder buffer, WebSocket queues (16),
webhook queue (1 000), forwarder queue (50 000). Nothing waits on a slow consumer.

## 6. Module map

| Module | Responsibility |
|---|---|
| `models.py` | Enums, `Detection` (wire), `Measurement`, `ClassPosterior`, API outputs, `Zone`, `SensorConfig` |
| `geo.py` | WGS-84 ↔ ENU, polar ↔ ENU with covariance |
| `config.py` | Typed settings (unknown keys are errors), TOML loader, env override |
| `fusion/` | Conversion (polar / angular / geodetic), reorder buffer, batching |
| `tracking/` | Kalman/EKF primitives, measurement linearisations, IMM, `Track`, `MultiTargetTracker` |
| `classification/` | Micro-Doppler synthesis, features, logistic model |
| `alerts/` | Zones, alert state machine, risk |
| `security/` | API keys + roles, rate limit + lockout, HMAC signing + replay cache, WS tickets, audit chain |
| `storage/` | `Store` protocol, memory + SQLite |
| `pipeline.py` | Orchestrator; ingest guard; deterministic |
| `runtime.py` | Async tick, servers, hub, retention |
| `api/` | FastAPI app (RBAC), ASGI guards (headers, body limit, request id), WebSocket hub, Prometheus |
| `notify.py` | Signed webhooks |
| `forwarder.py` | Edge-node collector/forwarder |
| `logsetup.py` | Text/JSON logging with request ids |
| `sim/`, `radar/`, `bench.py` | Simulator + scoring, range equation, benchmark |

## 7. Key decisions and the evidence behind them

| Decision | Reason / measurement |
|---|---|
| ENU + covariance as the only tracker input | One tracker for radar, Remote ID, RF, EO/IR |
| Deterministic synchronous core | Replay, simulation, tests and live share code; bit-identical replays |
| IMM (quiet + manoeuvre) | 8-seed ablation: horizontal RMSE 10.2 → 7.7 m with Doppler, fewer false tracks |
| Doppler σ = 1.5 m/s, not 0.3 | σ = 0.5 raised ID switches 4 → 24 (over-confident velocity); 1.5 fixed it and still improved RMSE |
| Bearings refine confirmed tracks only | Allowing tentative/coasting tracks produced false confirmations and ghosts |
| 5 hits to confirm | 4-seed test: false tracks 3.5 → 1.0 per run, accuracy unchanged |
| Drop tracks > 70 m/s; merge by 6-D χ² | Ghost tracks fed by neighbouring plots had 85 m/s "velocities" and never merged |
| Signed ingest + replay cache + skew window | Unsigned UDP is spoofable; signatures give authenticity; skew + cache stop replays |
| Hashed API keys, roles, lockout, WS tickets | No plaintext secrets at rest; least privilege; no keys in URLs |
| Hash-chained audit log | Tamper evidence without external infrastructure |
| Drop-oldest back-pressure | A slow consumer must never stall tracking |
| SQLite first, `Store` protocol | Zero-dependency edge deployments; seam for TimescaleDB |

## 8. Extension points

| To add… | Do this |
|---|---|
| A sensor | Register it (config / `POST /api/v1/sensors`); emit `Detection` JSON; optional per-sensor secret |
| A new sensor physics | Add a `*_lin` in `tracking/meas.py` and a conversion branch in `fusion/measurement.py` |
| A classifier (CNN) | Implement `predict_proba(iq, prf_hz) -> probs[drone, bird, clutter]`, pass `Pipeline(classifier=…)` |
| A motion model | Add a σ pair to `imm_sigma_*` (or extend `Imm` with a non-CV model) |
| A store | Implement the `Store` protocol (`docs/timescale_schema.sql` is the starting schema) |
| An alert channel | Subscribe with `Pipeline.add_alert_listener` (webhooks do exactly this) |
