# Radar and sensor primer for drone detection

How the sensor landscape maps to this backend. Ranges are typical figures for planning; real
performance depends on target RCS, clutter, weather, antenna height and the specific product. Commercial
systems report micro-drone detection at roughly 2–10 km; always confirm with a vendor datasheet and a
site trial.

## 1. Sensor types

| Type | Typical range | Strengths | Weaknesses | Best for |
|---|---|---|---|---|
| **FMCW** (frequency-modulated continuous wave) | 0.5 – 3 km | No near-range blind zone, compact, low power, fine range resolution | Shorter range; leakage and clutter handling | Perimeters, prisons, campuses, critical sites |
| **Pulse-Doppler** | 5 – 20 km | Long range; strong ground-clutter rejection | Near-range eclipsing blind zone; larger and costlier | Airports, defence, wide-area |
| **Phased array (AESA / MESA)** | 1 – 10 km | Electronic scanning (no moving parts), simultaneous multi-target tracking, very high update rate, 360° with panels | Cost, calibration, thermal design | Continuous 360° tracking of many targets |
| **Micro-Doppler** (a *processing mode*) | n/a | Rotor/wing signature separates drones from birds; > 97 % reported with AI on real data | Needs dwell time, SNR and band-specific training | Classification on any coherent radar |
| **Passive** (DVB-T / 4G / 5G illuminators, ISAC) | 2 – 10+ km | Non-emitting, covert, cheap, reuses infrastructure | Depends on illuminator geometry; lower accuracy | Low-cost dense networks |
| **RF detection / DF** | 1 – 10 km | Finds control/video links, sometimes the pilot | Blind to autonomous / link-silent drones | Complement to radar |
| **Remote ID receiver** | ~1 – 3 km | Identity + position from cooperative drones | Cooperative only; spoofable | Identity / compliance |
| **EO/IR (PTZ)** | 1 – 3 km | Visual confirmation, evidence | Weather/light; narrow FOV | Cued confirmation |
| **Acoustic arrays** | 0.3 – 1 km | Passive, cheap, works behind obstacles | Short range, noise sensitive | Dense local coverage |

The same table is available from the CLI: `sdt-radar catalog`.

## 2. Bands

**X (8–12 GHz)** or **Ku (12–18 GHz)** give a good range/resolution balance for targets of RCS ≈ 0.01 m²
(DJI-class). Higher bands improve resolution and micro-Doppler visibility (Doppler shift ∝ frequency)
but suffer more from rain attenuation. The packaged classifier assumes **X band** (10 GHz).

## 3. Sizing a radar: the range equation

```
R_max⁴ = Pt · G² · λ² · σ · G_int / ( (4π)³ · k · T · B · F · L · SNR_min )
```

`sdt-radar budget` implements it (`radar/equation.py`):

```bash
sdt-radar budget --power-w 10 --gain-dbi 35 --freq-ghz 10 --bandwidth-mhz 5 --integration-db 30
# max detection range (0.01 m² at SNR>=13.0 dB): 3,457 m
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
| Update rate ≤ 1–3 s | Radar scan rate + software | Pipeline handles 0.5–2 s scans (measured ~1 ms per scan on the perimeter scenario, ~112 ms for 500 targets) |
| Pd ≥ 90 % | Hardware Pd + tracker continuity | Coasting/re-acquisition; simulator scores track-level detection ≥ 99 % |
| Low false alarms | Both | M-of-N confirmation, speed plausibility, micro-Doppler class, bird suppression |
| Tens–hundreds of tracks | Software | 500 targets @ 112 ms/scan |
| Visualisation latency < 500 ms | Software | ~250 ms ingest→tracked, 200 ms snapshots |
| Distinguish drones from birds | Radar coherence + software | `classification/` (synthetic-trained; retrain on real data) |
| Multi-sensor fusion | Software | One ENU+covariance interface for radar, RF, Remote ID, EO/IR fixes; bearing-only EO/IR / acoustic / DF refine tracks natively |
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
Stone Soup and filterpy are good references for more advanced tracking (JPDA, MHT, non-linear models) — this
repository implements its own compact IMM tracker with no extra dependencies.
