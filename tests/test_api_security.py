import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from sdt_radar.api import create_app
from sdt_radar.security import AuditLog, Role, generate_key
from tests.helpers import SITE, polar_det, sensor_cfg, settings_for

ZONE = {"id": "z1", "name": "Z", "kind": "circle", "center_lat": SITE.lat, "center_lon": SITE.lon, "radius_m": 500}


@pytest.fixture
def env(tmp_path):
    keys = {r: generate_key(Role[r], r[:1] + "1") for r in ("viewer", "operator", "admin")}
    s = sensor_cfg("r1")

    def make(**api_over):
        api = {"keys": [rec for _, rec in keys.values()], "rate_limit_per_s": 1000.0, "rate_limit_burst": 2000.0}
        api.update(api_over)
        settings = settings_for(s, api=api, audit={"enabled": True, "path": str(tmp_path / "audit.jsonl")},
                                ingest={"udp_port": None, "tcp_port": None})
        return TestClient(create_app(settings))

    return make, {r: {"x-api-key": t} for r, (t, _) in keys.items()}, s, tmp_path / "audit.jsonl"


def test_rbac_matrix(env):
    make, h, s, _ = env
    with make() as c:
        det = [polar_det(s, np.array([1500.0, 500.0, 90.0]), time.time()).model_dump(mode="json", exclude_none=True)]
        sensor = sensor_cfg("r2", east=50).model_dump(mode="json")
        cases = [  # (method, path, json, minimal role)
            ("get", "/api/v1/tracks", None, "viewer"), ("get", "/api/v1/zones", None, "viewer"),
            ("get", "/api/v1/sensors", None, "viewer"), ("get", "/api/v1/metrics", None, "viewer"),
            ("get", "/api/v1/auth/whoami", None, "viewer"), ("post", "/api/v1/zones", ZONE, "operator"),
            ("post", "/api/v1/ingest/detections", det, "operator"), ("delete", "/api/v1/zones/z1", None, "operator"),
            ("post", "/api/v1/sensors", sensor, "admin"), ("get", "/api/v1/audit", None, "admin"),
            ("get", "/api/v1/audit/head", None, "admin"),
        ]
        rank = {"viewer": 1, "operator": 2, "admin": 3}
        for method, path, body, need in cases:
            assert getattr(c, method)(path, **({"json": body} if body is not None else {})).status_code == 401, path
            for role in ("viewer", "operator", "admin"):
                r = getattr(c, method)(path, headers=h[role], **({"json": body} if body is not None else {}))
                if rank[role] >= rank[need]:
                    assert r.status_code in (200, 201, 204, 404), (method, path, role, r.status_code, r.text)  # 404 = authorised, zone already deleted
                else:
                    assert r.status_code == 403, (method, path, role)
        assert c.get("/api/v1/auth/whoami", headers=h["operator"]).json() == {"key_id": "o1", "role": "operator"}


def test_lockout_blocks_even_valid_keys_and_rate_limit(env):
    make, h, _, _ = env
    with make(lockout_failures=3, lockout_s=60) as c:
        for _ in range(3):
            assert c.get("/api/v1/tracks", headers={"x-api-key": "sdtr_v1_wrong"}).status_code == 401
        r = c.get("/api/v1/tracks", headers=h["viewer"])
        assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1  # brute force => locked out
    with make(rate_limit_per_s=1.0, rate_limit_burst=3.0) as c:
        codes = [c.get("/api/v1/tracks", headers=h["viewer"]).status_code for _ in range(8)]
        assert codes[:3] == [200, 200, 200] and 429 in codes


def test_websocket_tickets_single_use_and_query_keys_refused(env):
    make, h, _, _ = env
    token = h["viewer"]["x-api-key"]
    with make() as c:
        t1 = c.post("/api/v1/auth/ws-ticket", headers=h["viewer"]).json()["ticket"]
        with c.websocket_connect(f"/ws/v1/stream?ticket={t1}") as ws:
            assert ws.receive_json()["type"] == "hello"
        with pytest.raises(Exception), c.websocket_connect(f"/ws/v1/stream?ticket={t1}") as ws:  # noqa: B017
            ws.receive_json()  # already used
        with pytest.raises(Exception), c.websocket_connect(f"/ws/v1/stream?api_key={token}") as ws:  # noqa: B017
            ws.receive_json()
        with c.websocket_connect("/ws/v1/stream", headers=h["viewer"]) as ws:
            assert ws.receive_json()["type"] == "hello"
    with make(allow_query_api_key=True) as c:  # explicit opt-in restores the legacy behaviour
        with c.websocket_connect(f"/ws/v1/stream?api_key={token}") as ws:
            assert ws.receive_json()["type"] == "hello"


def test_hardening_headers_body_limit_request_id_and_host_allowlist(env):
    make, h, _, _ = env
    with make(max_body_bytes=2000, allowed_hosts=["testserver", "good.example"]) as c:
        r = c.get("/api/v1/tracks", headers=h["viewer"])
        assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
        assert r.headers["cache-control"] == "no-store" and "default-src 'none'" in r.headers["content-security-policy"]
        assert "strict-transport-security" not in r.headers and "server" not in r.headers
        assert len(r.headers["x-request-id"]) >= 8
        assert c.get("/health", headers={"x-request-id": "trace-abcdef123456"}).headers["x-request-id"] == "trace-abcdef123456"
        assert c.get("/health", headers={"x-request-id": "bad id!"}).headers["x-request-id"] != "bad id!"
        big = [{"sensor_id": "r1", "t": 1.0, "pad": "x" * 100}] * 100
        assert c.post("/api/v1/ingest/detections", headers=h["operator"], json=big).status_code == 413
        assert c.get("/health", headers={"host": "evil.example"}).status_code == 400  # Host header allow-list
    with make(tls_certfile="/tmp/x.pem", tls_keyfile="/tmp/x.key") as c:
        assert "strict-transport-security" in c.get("/health").headers  # HSTS when TLS is terminated here


def test_security_events_land_in_a_verifiable_audit_log(env):
    make, h, s, audit_path = env
    with make() as c:
        c.get("/api/v1/tracks", headers={"x-api-key": "sdtr_v1_nope"})  # auth failure
        c.post("/api/v1/zones", headers=h["viewer"], json=ZONE)  # forbidden
        c.post("/api/v1/zones", headers=h["operator"], json=ZONE)  # zone_create
        c.delete("/api/v1/zones/z1", headers=h["operator"])  # zone_delete
        c.post("/api/v1/sensors", headers=h["admin"], json=sensor_cfg("r9", east=10).model_dump(mode="json"))
        rows = c.get("/api/v1/audit", headers=h["admin"]).json()
        actions = [r["action"] for r in rows]
        assert actions == ["auth_failure", "forbidden", "zone_create", "zone_delete", "sensor_register"]
        assert rows[2]["actor"] == "o1" and rows[2]["role"] == "operator" and rows[2]["detail"]["zone_id"] == "z1"
        assert rows[0]["actor"] == "-" and rows[0]["ip"]
        head = c.get("/api/v1/audit/head", headers=h["admin"]).json()
        assert head["seq"] == 5 and len(head["hash"]) == 64
    rep = AuditLog.verify(audit_path)
    assert rep.ok and rep.records >= 5


def test_sensor_registration_never_leaks_secrets_and_fails_closed(env, monkeypatch):
    make, h, _, _ = env
    monkeypatch.setenv("SDT_R7_SECRET", "z" * 32)
    with make() as c:
        body = sensor_cfg("r7", east=20, hmac_secret_env="SDT_R7_SECRET").model_dump(mode="json")
        r = c.post("/api/v1/sensors", headers=h["admin"], json=body)
        assert r.status_code == 201 and "hmac_secret_env" not in r.json()
        listed = {x["id"]: x for x in c.get("/api/v1/sensors", headers=h["viewer"]).json()}
        assert listed["r7"]["signed"] is True and listed["r1"]["signed"] is False
        assert "hmac_secret_env" not in listed["r7"] and "z" * 32 not in str(listed)
        missing = sensor_cfg("r8", east=30, hmac_secret_env="SDT_DOES_NOT_EXIST").model_dump(mode="json")
        assert c.post("/api/v1/sensors", headers=h["admin"], json=missing).status_code == 422


def test_prometheus_endpoint_requires_auth_unless_public(env):
    make, h, s, _ = env
    with make() as c:
        assert c.get("/metrics").status_code == 401
        det = [polar_det(s, np.array([1500.0, 500.0, 90.0]) + np.array([-15.0, -5, 0]) * k, time.time() - 8 + k)
               .model_dump(mode="json", exclude_none=True) for k in range(8)]
        c.post("/api/v1/ingest/detections", headers=h["operator"], json=det)
        end = time.time() + 5
        while time.time() < end and 'sdt_tracks{status="confirmed"}' not in c.get("/metrics", headers=h["viewer"]).text:
            time.sleep(0.1)
        text = c.get("/metrics", headers=h["viewer"]).text
        assert "# TYPE sdt_tracks gauge" in text and 'sdt_tracks{status="confirmed"} 1' in text
        assert "sdt_detections_received_total 8" in text and 'sdt_sensor_last_seen_age_seconds{sensor="r1"}' in text
        assert "sdt_uptime_seconds" in text and text.endswith("\n")
    with make(metrics_public=True) as c:
        assert c.get("/metrics").status_code == 200
