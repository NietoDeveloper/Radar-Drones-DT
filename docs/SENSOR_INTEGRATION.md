# Integrating real sensors

The backend never talks to hardware. A **sensor adapter** (a small process or thread you own) translates a
vendor SDK or protocol into `Detection` JSON and sends it to the ingest ports. This keeps vendor code,
licences and crashes out of the tracking service.

> The adapter skeletons below are illustrative starting points, not shipped or tested drivers.

## 1. Step by step

1. **Survey the sensor.** Position (lat, lon, altitude of the antenna phase centre), where azimuth 0
   points relative to true North, range/azimuth/elevation noise (datasheet or measured), scan period.
2. **Register it** in `[[sensors]]` or `POST /api/v1/sensors`:
   `north_offset_deg` is *added* to the azimuth the radar reports to reference true North.
3. **Write the adapter**: read plots (or tracks) from the SDK/UDP feed, convert units, emit one JSON per
   detection with the **sensor's measurement timestamp** (not the receive time).
4. **Send** via UDP (lowest overhead), TCP (reliable stream) or HTTP.
5. **Verify** with `GET /api/v1/sensors` (counts, `last_seen_age_s`) and `/api/v1/metrics`
   (`rejected_*` must stay 0).
6. **Record** raw detections (`storage.recorder_path`) and replay them to tune the tracker.

## 2. Plots or tracks?

Prefer **plots** (unfiltered detections). The backend's tracker then fuses sensors with proper
covariances. If a radar only exposes its own tracks, send those as detections too (each carries the
radar's already-filtered position, so its noise is *lower and correlated*: lower `sigma_*` carefully, or
use it as a single-sensor feed). Do not feed the same target as both plots and tracks from one radar.

## 3. Conventions that bite

| Topic | Convention here | Common mistake |
|---|---|---|
| Azimuth | Degrees, **clockwise from true North** | Math convention (CCW from East) |
| Elevation | Up positive from the local horizontal | Sensor tilt not removed |
| Range | Slant range, metres | Ground range |
| Time | Epoch seconds, **measurement time**, clocks synced (NTP/PTP) | Using receive time; skewed clocks |
| Altitude | Ellipsoidal, metres | Mixing MSL / AGL |
| Radial velocity | Positive receding | Sign flipped |
| Units | SI everywhere; dBsm for RCS | Mixed units |

## 4. Skeleton: UDP radar adapter

```python
import json, socket, time

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
TARGET = ("127.0.0.1", 9100)

def on_vendor_plot(p):                        # called by the vendor SDK
    det = {
        "sensor_id": "fmcw-1",
        "t": p.timestamp_unix,                # measurement time, UTC
        "range_m": p.range_m,
        "azimuth_deg": p.azimuth_deg,         # adapter converts to clockwise-from-North if needed
        "elevation_deg": p.elevation_deg,
        "radial_velocity_mps": p.doppler_mps,
        "rcs_dbsm": p.rcs_dbsm,
        "snr_db": p.snr_db,
    }
    sock.sendto(json.dumps([det]).encode(), TARGET)   # batch several plots per datagram when possible
```

## 5. Micro-Doppler payload

If the radar can export the slow-time I/Q of the range cell around a detection:

```python
import numpy as np
from sdt_radar.models import encode_iq
det["md_prf_hz"] = 10_240.0                   # pulse repetition frequency of the dwell
det["md_iq_b64"] = encode_iq(iq_complex64)    # ≥ 256 samples; 1024 is a good default
```

The packaged classifier was trained for X-band with PRF 10–16 kHz and a ~0.1 s dwell
(see CLASSIFICATION.md). Send a dwell only for detections you want classified (e.g. every 2nd–5th plot).

## 5b. Signing a sensor's data (recommended over UDP/TCP)

Give each sensor its own secret (environment variable or file, never the config text) and sign every
detection so the hub can authenticate it, detect tampering and reject replays:

```python
from sdt_radar.security import sign
det = {"sensor_id": "fmcw-1", "t": time.time(), "range_m": 1843.2, "azimuth_deg": 211.4, "elevation_deg": 6.1}
det["sig"] = sign(SECRET_BYTES, det)          # HMAC-SHA256 over canonical JSON (sorted keys, no spaces, None omitted)
sock.sendto(json.dumps([det]).encode(), HUB)  # send exactly what you signed (same numbers, same types)
```

Hub side: `hmac_secret_env = "SDT_FMCW1_SECRET"` on the sensor (or `ingest.require_signatures = true`).
Unsigned, wrongly signed, replayed or stale (> `ingest.max_clock_skew_s`, 30 s) detections are rejected and
counted. Non-Python senders must reproduce the canonical JSON exactly (shortest round-trip number formatting).

## 5c. Edge nodes: the forwarder

For distributed networks of cheap SDR / edge nodes, run `sdt-radar forward` next to the sensors. It collects
UDP/TCP JSON locally, signs per sensor, batches, and ships over **HTTPS** to the hub with an operator key.
A bounded queue sheds the oldest data during outages (counted); auth errors are never retried.

```bash
export OPKEY='sdtr_edge7_…'            # operator-role key created with `sdt-radar keygen`
export S_FMCW1='…'                     # same secret the hub holds for sensor fmcw-1
sdt-radar forward --hub https://radar-hub:8443 --cafile /etc/ssl/private-ca.pem \
                  --api-key-env OPKEY --sign fmcw-1=S_FMCW1 --listen-udp 9100
```

The hub verifies the certificate (system CAs or `--cafile`; verification is never disabled), the key's role,
and each detection's signature — so a stolen operator key alone cannot inject data for a signed sensor.

## 6. Other source types

| Source | How it enters | Notes |
|---|---|---|
| **Remote ID** receiver | Geodetic detection, `sigma_h_m` ≈ GNSS error (3–10 m), `external_id` = serial | Cooperative drones only; position is self-reported (spoofable) — fuse, don't trust |
| **RF detector / DF** | Geodetic detection if it geolocates (large `sigma_h_m`, e.g. 30–100 m) | Bearing-only RF must be triangulated upstream |
| **EO/IR cameras** | **Angular detection** (`azimuth_deg` + `elevation_deg`, no range) from a registered `eo_ir` sensor; set realistic `sigma_az_deg` / `sigma_el_deg` (0.1–0.3° typical) | Fused natively: refines **confirmed** tracks (cross-range accuracy), cannot start a track |
| **Acoustic array / RF direction finder** | Angular detection (bearing of the array / DF) | Same; if the device also estimates range or position, send a geodetic fix instead |
| **Passive radar** | Polar or geodetic plots from the passive processing chain | Set noise conservatively |
| **SAPIENT / ASTERIX** | A bridge process decodes and emits detections | Not included in v1 |

## 7. Multi-radar sites

Each radar is its own `sensor_id` with its own position and noise. The tracker associates each sensor's
batch separately and weights every update by that sensor's covariance, so overlapping radars sharpen the
picture (measured: two independent sensors reduce position error vs. one — see `tests/test_tracking.py`).
Keep `north_offset_deg` accurate: a 1° azimuth error is 35 m at 2 km and shows up as persistent
disagreement between radars.

## 8. Time synchronisation

Run NTP (or PTP for tight sites) on every sensor host and on the backend. Symptoms of skew:
`stale_measurements` rising (sensor behind), latency percentiles growing with `buffer_len` (sensor ahead),
two radars' tracks of one target failing to merge.

## 9. Acceptance checklist

* `rejected_invalid`, `rejected_sensor`, `rejected_malformed` stay at 0 during a flight.
* A cooperative drone flown on a known path shows a track within a few metres (Remote ID) / tens of
  metres (radar) of GNSS truth, in the right direction (swap-checks catch azimuth convention errors).
* Radars at the same site agree on a common target within their stated σ.
* `GET /api/v1/sensors` shows `last_seen_age_s` of about the scan period.
