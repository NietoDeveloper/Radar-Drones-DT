# Changelog

## 2.0.0

### Tracking
* **IMM estimator** (quiet + manoeuvre constant-velocity models) with exact per-second model switching.
* **Doppler-aided updates** from radar radial velocity (gated; default noise 1.5 m/s).
* **Bearing-only fusion** (EO/IR, acoustic, RF direction finders): new *angular* detection geometry, EKF
  update in angle space; refines confirmed tracks only and never changes existence evidence.
* Kinematic plausibility: confirmation requires 5 hits (was 4); tracks faster than 70 m/s are dropped;
  statistical duplicate merging no longer blocked by a velocity-difference clause.
* Measured (8 simulated perimeter scenarios): horizontal RMSE 10.2 → 7.7 m (5.5 m with EO/IR), vertical
  12.7 → 11.0 m (5.7 m with EO/IR), ID switches 2.9 → 4.5 (1.4 with EO/IR), never-matched false tracks
  1.1 → 0.25 per 150 s; 500-target swarm ID switches 83 → 43, step time p50 73 → 112 ms.

### Security
* **API keys with roles** (viewer / operator / admin), stored only as SHA-256 hashes, constant-time checks; `sdt-radar keygen`.
* Per-IP **rate limiting** and **brute-force lockout**; request-size limit; Host allow-list; hardening headers; TLS flags.
* **Single-use WebSocket tickets**; `?api_key=` refused by default.
* **Per-sensor HMAC-signed ingest** with clock-skew window, replay cache, fail-closed secrets and per-sensor rate limits.
* **Tamper-evident audit log** (hash chain) + `sdt-radar audit-verify` + `/api/v1/audit`.
* The CLI refuses to expose the API without authentication.

### Operations and integration
* Prometheus `/metrics`; structured JSON logs with request ids; automatic retention pruning.
* **Signed webhooks** for alerts (retry/back-off, bounded queue).
* **Edge forwarder** (`sdt-radar forward`): sign, batch, HTTPS to a hub, bounded buffering during outages.
* `udp_enabled` / `tcp_enabled` switches; sensors report `signed` status; secrets never returned by the API.

### Breaking changes
* WebSocket `?api_key=` no longer works unless `api.allow_query_api_key = true` (use tickets or the header).
* `/api/v1/ingest/detections`, zone writes and sensor registration now need operator/admin roles when keys are configured.
* Defaults changed: `confirm_hits` 4 → 5, `gate_chi2` stays 21.1, sensors' `sigma_radial_velocity_mps` 1.5.
* The audit log is on by default (`data/audit.jsonl`).

## 1.0.0
Initial release: ingestion, GNN Kalman tracker, micro-Doppler classifier, zone alerts, SQLite store,
REST + WebSocket API, simulator, benchmark.
