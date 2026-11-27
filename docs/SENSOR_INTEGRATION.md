# Integrating real sensors

The backend never talks to hardware. A **sensor adapter** (a small process or thread you own) translates a
vendor SDK or protocol into `Detection` JSON and sends it to the ingest ports. This keeps vendor code,
licences and crashes out of the tracking service.

> The adapter skeletons 
        "sensor_id"tween radars.

## 8. Time synchronisation

Run NTP (or PTP for tight sites) on every sensor host and on the backend. Symptoms of skew:
`stale_measurements`one flown on a known path shows a track within a few metres (Remote ID) / tens of
  metres (radar) of GNSS truth, in the right direction (swap-checks catch azimuth convention errors).
* Radars at the same site agree on a common target within their stated σ.
* `GET /api/v1/sensors` shows `last_seen_age_s` of about the scan period.
