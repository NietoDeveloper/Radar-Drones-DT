import json
import socket
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from sdt_radar.api import create_app
from sdt_radar.models import Zone
from sdt_radar.pipeline import Pipeline
from tests.helpers import SITE, polar_det, sensor_cfg, settings_for


def det_stream(sensor, now, n=8, p0=(1500.0, 500.0, 90.0), v=(-15.0, -5.0, 0.0)):
    """n radar plots of one drone, 1 Hz, ending at `now` (timestamps are recent, as in a live feed)."""
    return [polar_det(sensor, np.array(p0) + np.array(v) * k, now - (n - 1 - k)).model_dump(mode="json", exclude_none=True)
            for k in range(n)]


def make_client(api_key=None, udp=False, zones=()):
    s = sensor_cfg("r1")
    settings = settings_for(s, zones=list(zones), api={"api_key": api_key},
                            ingest={"udp_port": 0 if udp else None, "tcp_port": 0 if udp else None})
    return s, TestClient(create_app(settings))


def wait_for(fn, timeout=5.0, step=0.05):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    raise AssertionError("condition not met in time")


def test_health_is_open_and_api_requires_key_when_configured():
    _, c = make_client(api_key="s3cret")
    with c:
        assert c.get("/health").json()["status"] == "ok"
        assert c.get("/api/v1/tracks").status_code == 401
        assert c.get("/api/v1/tracks", headers={"x-api-key": "wrong"}).status_code == 401
        assert c.get("/api/v1/tracks", headers={"x-api-key": "s3cret"}).status_code == 200
        with pytest.raises(Exception), c.websocket_connect("/ws/v1/stream") as ws:  # noqa: B017
            ws.receive_json()
        with c.websocket_connect("/ws/v1/stream?api_key=s3cret") as ws:
            assert ws.receive_json()["type"] == "hello"


def test_rest_ingest_tracks_history_archive_and_errors():
    s, c = make_client()
    with c:
        now = time.time()
        r = c.post("/api/v1/ingest/detections", json=det_stream(s, now) + [{"sensor_id": "r1", "t": 1}, {"junk": True}])
        assert r.json() == {"accepted": 8, "rejected": 2}
        tracks = wait_for(lambda: c.get("/api/v1/tracks").json())
        t = tracks[0]
        assert t["status"] == "confirmed" and t["sensors"] == ["r1"] and t["speed_mps"] > 5
        assert c.get("/api/v1/tracks?target_class=bird").json() == []
        assert c.get("/api/v1/tracks?min_confidence=0.99").json() == []
        one = c.get(f"/api/v1/tracks/{t['track_id']}").json()
        assert one["track_id"] == t["track_id"]
        hist = wait_for(lambda: c.get(f"/api/v1/tracks/{t['track_id']}/history").json())
        assert hist[0]["t"] <= hist[-1]["t"] and {"lat", "lon", "alt_m", "speed_mps"} <= set(hist[0])
        assert c.get("/api/v1/tracks/doesnotexist").status_code == 404
        assert c.get("/api/v1/tracks/doesnotexist/history").status_code == 404
        assert c.get("/api/v1/tracks?min_confidence=2").status_code == 422
        assert c.post("/api/v1/ingest/detections", json=[{}] * 5001).status_code == 413
        arch = wait_for(lambda: c.get("/api/v1/archive/tracks").json())
        assert arch[0]["track_id"] == t["track_id"]
        m = c.get("/api/v1/metrics").json()
        assert m["counters"]["received"] == 8 and m["counters"]["rejected_invalid"] == 2 and m["classifier"]
        sens = c.get("/api/v1/sensors").json()
        assert sens[0]["id"] == "r1" and sens[0]["detections"] == 8


def test_zone_crud_sensor_registration_and_alerts_over_rest():
    s, c = make_client()
    with c:
        z = {"id": "core", "name": "Core", "kind": "circle", "center_lat": SITE.lat, "center_lon": SITE.lon,
             "radius_m": 3000, "level": "critical"}
        assert c.post("/api/v1/zones", json=z).status_code == 201
        assert c.post("/api/v1/zones", json={**z, "radius_m": None}).status_code == 422
        assert [x["id"] for x in c.get("/api/v1/zones").json()] == ["core"]
        c.post("/api/v1/ingest/detections", json=det_stream(s, time.time()))
        alerts = wait_for(lambda: c.get("/api/v1/alerts?active=true").json())
        assert alerts[0]["zone_id"] == "core" and alerts[0]["state"] == "open"
        assert c.delete("/api/v1/zones/core").status_code == 204
        assert c.delete("/api/v1/zones/core").status_code == 404
        new = sensor_cfg("r2", east=100).model_dump(mode="json")
        assert c.post("/api/v1/sensors", json=new).status_code == 201
        assert {x["id"] for x in c.get("/api/v1/sensors").json()} == {"r1", "r2"}


def test_websocket_stream_snapshot_filters_and_alert_push():
    s, c = make_client(zones=[Zone(id="core", name="Core", kind="circle", center_lat=SITE.lat, center_lon=SITE.lon, radius_m=3000)])
    with c, c.websocket_connect("/ws/v1/stream") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["protocol"] == 1
        c.post("/api/v1/ingest/detections", json=det_stream(s, time.time()))
        seen_alert, snap = False, None
        end = time.time() + 6
        while time.time() < end and not (seen_alert and snap):
            msg = ws.receive_json()
            if msg["type"] == "alert":
                seen_alert = msg["alert"]["type"] in ("zone_intrusion", "zone_approach")
            if msg["type"] == "snapshot" and msg["count"] == 1:
                snap = msg
        assert seen_alert and snap and snap["tracks"][0]["status"] == "confirmed"
        ws.send_json({"subscribe": {"classes": ["bird"], "min_confidence": 0.1}})
        end = time.time() + 4
        while time.time() < end:
            msg = ws.receive_json()
            if msg["type"] == "subscribed":
                assert msg["classes"] == ["bird"]
            if msg["type"] == "snapshot" and msg["count"] == 0:
                break
        else:
            raise AssertionError("filtered snapshot never arrived")
        ws.send_json({"subscribe": {"classes": ["not-a-class"]}})
        err = wait_for(lambda: ws.receive_json()["type"] == "error")
        assert err


@pytest.mark.parametrize("n", [1])
def test_udp_and_tcp_ingest_end_to_end_with_latency_budget(n):
    s, c = make_client(udp=True)
    with c:
        rt = c.app.state.runtime
        pipe: Pipeline = c.app.state.pipeline
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        now = time.time()
        stream = det_stream(s, now, n=8)
        sock.sendto(json.dumps(stream[:4]).encode(), ("127.0.0.1", rt.udp.port))  # JSON array datagram
        for d in stream[4:6]:
            sock.sendto(json.dumps(d).encode(), ("127.0.0.1", rt.udp.port))  # single-object datagram
        with socket.create_connection(("127.0.0.1", rt.tcp.port)) as tcp:
            tcp.sendall(("\n".join(json.dumps(d) for d in stream[6:]) + "\nnot json\n").encode())
        wait_for(lambda: pipe.stats["received"] >= 8)
        assert pipe.stats["rejected_malformed"] >= 1
        t = wait_for(lambda: c.get("/api/v1/tracks").json())[0]
        assert t["status"] == "confirmed"
        lat = pipe.metrics()["latency_ms"]
        assert lat["p99"] < 500.0, lat  # ingest -> tracked, well inside the 500 ms display budget
