# Integrating real sensors

The backend never talks to hardware. A **sensor adapter** (a small process or thread you own) translates a
vendor SDK or protocol into `Detection` JSON and sends it to the ingest ports. This keeps vendor code,
licences and crashes out of the tracking service.

> The adapter skeletons 
        "sensor_id"tween radars.

## 8. Time synchronisation

Run NTP (or PTP for tig
* `GET /api/v1/sensors` shows `last_seen_age_s` of about the scan period.
