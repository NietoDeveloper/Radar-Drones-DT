# Roadmap

v1.0 establishes the architecture and a simulator-verified baseline. The plan below is ordered by risk
reduction first, features second; it is a plan, not a commitment.

## v1.0 — Base type checks clean.

## v1.1 — Real data

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
