# Roadmap

Delivered work is recorded in [CHANGELOG.md](../CHANGELOG.md). This plan is ordered by risk reduction first,
features second; it is a plan, not a commitment.

## v2.0 — delivered

IMM tracker, Doppler-aided updates, bearing-only (EO/IR / acoustic / DF) fusion; hashed API keys with roles,
lockout and rate limits, WebSocket tickets, signed ingest with replay protection, hash-chained audit log,
hardening headers; Prometheus, structured logs, retention, signed webhooks, edge forwarder with HTTPS.

## v2.1 — real data and storage

* Reference adapters for one commercial radar SDK and a Remote ID receiver; SAPIENT bridge.
* Recorded-data tooling: label dwells, retrain the classifier, evaluate on held-out sites/days.
* TimescaleDB / PostgreSQL `Store` (schema in `docs/timescale_schema.sql`) with its own CI against a real server.
* Hot reload of API keys; key expiry; per-key rate limits.
* mTLS option for edge → hub links.

## v2.2 — tracking depth

* Coordinated-turn (non-linear) model inside the IMM; adaptive process noise per class (birds vs drones).
* Adaptive per-measurement covariance from SNR; association with class and RCS likelihoods.
* Track-to-track fusion for sensors that only expose their own tracks.
* Calibrated existence probability (replace the heuristic `confidence`).

## v3.0 — scale and advanced sensing

* Horizontal scaling: partitioned tracking by sector, multi-node fusion hub for distributed SDR nodes.
* CNN classifiers over range-Doppler and spectrograms (ONNX runtime), per-band models, drift monitoring.
* Passive-radar (DVB-T/4G/5G) and RF-fingerprint processing chains feeding position fixes.
* PTZ cueing API (slew-to-track for EO/IR confirmation); evidence export for incident reports.
* OIDC/SSO and user accounts; encryption at rest; formal threat-model review and external penetration test.

## Cross-cutting

* Every behaviour change ships with a scenario test and updated measurements in the README.
* Replays of recorded data are the regression suite for tracker tuning.
* Limitations stay documented next to the claims they qualify.
