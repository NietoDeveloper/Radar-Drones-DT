# Integrating real sensors

The backend never talks to hardware. A **sensor adapter** (a small process or thread you own) translates a
vendor SDK or protocol into `Detection` JSON and sends it to the ingest ports. This keeps vendor code,
licences and crashes out of the tracking service.

> The adapter skeletons 
        "sensor_id": "fmcw-1",
        "t": p.times restriction |
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
