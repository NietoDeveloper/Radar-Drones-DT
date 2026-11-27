# Radar and sensor primer for drone detection

How the sensor landscape maps to this backend. Ranges are typical figuresrange (0.01 m² at SNR>=13.0 dB): 3,457 m
# range resolution: 29.98 m   velocity resolution (50 ms dwell): 0.30 m/s
```

Rules of thumb it encodes: range scales with the **fourth root** of power and RCS; SNR falls
**40 dB per decade** of range; halving bandwidth buys 3 dB; coherent integration adds gain at the cost of
dwell time. `peak_power_w` is the *effective* power over the dwell (average power for FMCW; peak × duty ×
pulses for pulsed radars). Treat the output as a first-order estimate.

## 4. Requirements and where each is addressed

| Requirement | Hardware or software? | Where / how |
|---|---|---|
| Detect RCS 0.01 m² at ≥ 2–5 km | **Hardware** (power, gain, band, integration) | `sdt-radar budget`; vendor datasheet; site trial |
| Update rate ≤ 1–3 s | Radar scan rate + software | Pipeline handles 0.5–2 s scans (measured 1–73 ms per scan) |
| Pd ≥ 90 % | Hardware Pd + tracker continuity | Coasting/re-acquisition; simulator scores track-level detection ≥ 98.6 % |
| Low false alarms | Both | M-of-N confirmation, speed plausibility, micro-Doppler class, bird suppression |
| Tens–hundreds of tracks | Software | 500 targets @ 73 ms/scan |
| Visualisation latency < 500 ms | Software | ~250 ms ingest→tracked, 200 ms snapshots |
| Distinguish drones from birds | Radar coherence + software | `classification/` (synthetic-trained; retrain on real data) |
| Multi-sensor fusion | Software | One ENU+covariance interface for radar, RF, Remote ID, EO/IR fixes |
| Open interfaces (SAPIENT etc.) | Software | JSON ingest + adapter pattern (SENSOR_INTEGRATION.md) |
| Simulation / synthetic data before hardware | Software | `sim/` scenarios, micro-Doppler synthesis |
| Low-SWaP / low-cost nodes | Hardware | SDR + edge nodes feed the same ingest |

## 5. Suggested path

1. Pick a medium-range commercial FMCW or phased-array radar with an SDK that exposes plots/tracks.
2. Write a small adapter that emits `Detection` JSON (see SENSOR_INTEGRATION.md); register the sensor.
3. Run `serve`, point a map frontend at the WebSocket, record raw detections (`storage.recorder_path`).
4. Replay recordings (`sdt-radar replay`) to tune tracker gates and alert zones without flying.
5. Collect labelled micro-Doppler dwells (drone / bird / clutter) and retrain the classifier.
6. Add Remote ID / RF / EO-IR sources as position fixes; verify fusion improves accuracy on your site.
7. Move storage to TimescaleDB if retention/analytics require it (`docs/timescale_schema.sql`).

## 6. Open-source references for prototyping

Passive/RF/acoustic projects (e.g. tacet, passive-radar counter-drone work on DVB-T/4G/5G, VARTA for
acoustic) and SDR hardware (HackRF, USRP) are useful for building low-cost sensor nodes. They are
**not** dependencies of this repository; their outputs would enter through the ingest adapters.
Stone Soup and filterpy are good references for more advanced tracking (IMM, JPDA, MHT) — this repository
implements its own compact tracker with no extra dependencies.
