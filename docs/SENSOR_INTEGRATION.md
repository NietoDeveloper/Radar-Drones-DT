# Integrating real sensors

The backend never talks to hardware. A **sensor adapter** (a small process or thread you own) translates a
vendor SDK or protocol into `Detection` JSON and sends it to the ingest ports. This keeps vendor code,
licences and crashes out of the tracking service.

> The adapter skeletons below are illustrative sta

| Topic | Convention here | Common mistake |
|---|---|---|
    }
    sock.sendto(json.dumps([det]).encode(), TARGE
from sdt_radar.models import encode_iq
det["md_prf_hz"] = 10_240.0                   # pulse repetition frequency of the dwell
det["md_iq_b64"] = encode_iq(iq_complex64)    # ≥ 256 samples; 1024 is a good default
```

The packaged classifier was trained for X-band with PRF 10–16 kHz 