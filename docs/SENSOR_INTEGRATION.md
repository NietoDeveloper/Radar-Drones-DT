# Integrating real sensors

The backend never talks to hardware. A **sensor adapter** (a small process or thread you own) translates a
vendor SDK or protocol into `Detection` JSON and sends it to the ingest ports. This keeps vendor code,
licences and crashes out of the tracking service.

> The adapter skeletons below are illustrative starting points, not shipped or tested drivers.

## 1. Step by step

1. **Survey the sensor.** Position (lat, lon, altitude of the antenna phase centre), where azimuth 0

4. **Send** via UDP (lowest overhead), TCP (reliable stream) or HTTP.
5. **Verify** with `GET /api/v1/sensors` (counts, `last_seen_age_s`) and `/api/v1/metrics`

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

## 6. Other source types

| Source | How it enters | Notes |
|---|---|---|
| **Remote ID** receiver | Geodetic detection, `sigma_h_m` ≈ GNSS error (3–10 m), `external_id` = serial | Cooperative drones only; position is self-reported (spoofable) — fuse, don't trust |
| **RF detector / DF** | Geodetic detection if it geolocates (large `sigma_h_m`, e.g. 30–100 m) | Bearing-only RF must be triangulated upstream |
| **EO/IR + PTZ** | Geodetic detection from a ranging/triangulated fix | Bearing-only cameras are not fused natively in v1 |
| **Acoustic array** | Geodetic fix from the array's localisation | Same restriction |
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
