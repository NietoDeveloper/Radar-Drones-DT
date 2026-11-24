# Roadmap

v1.0 establishes the architecture and a simulator-verified baseline. The plan below is ordered by risk
reduction first, features second; it is a plan, not a commitment.

## v1.0 — Baseline (this release)

* Ingest (UDP/TCP/HTTP), strict validation, fusion of polar and geodetic sources, reorder buffer.
* GNN Kalman tracker with lifecycle, statistical merging, per-measurement covariance.
* Micro-Doppler classifier (synthetic-trained) with per-track evidence; zone alerts with risk and suppression.
* SQLite store with writer thread, JSONL audit log, deterministic replay; REST + WebSocket API with API key.
* Simulator, scoring, 500-target benchmark, radar-equation tool; 58 tests; lint and type checks clean.

## v1.1 — Real data

* Reference adapters for one commercial radar SDK and a Remote ID receiver; SAPIENT bridge.
* Recorded-data tooling: label dwells, retrain classifier, evaluate on held-out sites.
* TimescaleDB/PostgreSQL `Store` implementation (schema in `docs/timescale_schema.sql`), Redis queue option.
* Use of radial velocity in the filter (Doppler-aided tracking) and in association.

## v1.2 — Tracking quality

* IMM (constant-velocity + coordinated-turn) to cut fragmentation on manoeuvres (current weak point).
* Adaptive process noise per class (birds vs drones); per-sensor adaptive covariance from SNR.
* Bearing-only fusion (EO/IR, acoustic arrays) via EKF/UKF updates.
* Track-to-track fusion for sensors that only expose their own tracks.

## v2.0 — Scale and trust

* Horizontal scaling: partitioned tracking by sector, multi-node fusion hub for distributed SDR/edge nodes.
* TLS, user accounts/roles, audit trail of API actions, signed detections, rate limiting.
* Alerts: dwell-time, loitering, no-fly corridors, geofence schedules, webhook/MQTT/SMS delivery.
* Evidence export (track + raw detections + media references) for incident reports.

## v3.0 — Advanced sensing

* CNN classifiers over range-Doppler and spectrogram data (ONNX runtime), per-band models, drift monitoring.
* Passive-radar (DVB-T/4G/5G) and RF-fingerprint processing chains feeding position fixes.
* PTZ cueing: slew-to-cue API for EO/IR confirmation.
* Calibrated existence probability (replace the heuristic `confidence`).

## Cross-cutting, every release

* Every behaviour change ships with a scenario test and updated metrics in the README.
* Replays of recorded data are the regression suite for tracker tuning.
* Limitations stay documented next to the claims they qualify.
