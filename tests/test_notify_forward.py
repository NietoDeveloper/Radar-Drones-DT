import hashlib
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from sdt_radar.config import WebhookConfig
from sdt_radar.forwarder import Forwarder
from sdt_radar.models import AlertLevel, AlertOut, AlertType, TargetClass
from sdt_radar.notify import WebhookNotifier, signature
from sdt_radar.security import verify


class Hub:
    """A tiny HTTP server that records requests; ``fail_first`` makes the first N requests return 500."""

    def __init__(self, fail_first=0, reply=None):
        self.requests, self.fail_first, self.reply = [], fail_first, reply or {}
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers["content-length"]))
                outer.requests.append((self.path, {k.lower(): v for k, v in self.headers.items()}, body))
                if len(outer.requests) <= outer.fail_first:
                    self.send_response(500)
                    self.end_headers()
                    return
                out = json.dumps(outer.reply or {"accepted": len(json.loads(body)) if body.startswith(b"[") else 1,
                                                 "rejected": 0}).encode()
                self.send_response(200)
                self.send_header("content-length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def hub():
    h = Hub()
    yield h
    h.close()


def wait(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def alert(level=AlertLevel.critical, state="open"):
    return AlertOut(alert_id="a1", type=AlertType.zone_intrusion, level=level, state=state, track_id="t1", zone_id="z",
                    zone_name="Z", opened_at=1, updated_at=1, closed_at=None, risk=0.9, target_class=TargetClass.drone,
                    message="m", lat=1, lon=1, alt_m=1)


def test_webhook_is_signed_filtered_by_level_and_never_blocks(hub, monkeypatch):
    monkeypatch.setenv("SDT_HOOK_SECRET", "hook-secret")
    n = WebhookNotifier([WebhookConfig(url=hub.url + "/hook", secret_env="SDT_HOOK_SECRET", min_level=AlertLevel.warning)])
    n.start()
    n.notify(alert(AlertLevel.info))  # below min_level: not sent
    n.notify(alert(AlertLevel.critical))
    assert wait(lambda: n.stats["sent"] == 1)
    n.stop()
    path, headers, body = hub.requests[0]
    assert len(hub.requests) == 1 and path == "/hook" and headers["x-sdt-event"] == "alert"
    ts = headers["x-sdt-timestamp"]
    assert headers["x-sdt-signature"] == signature(b"hook-secret", ts, body)  # receiver can authenticate us
    expected = "sha256=" + hmac.new(b"hook-secret", ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert headers["x-sdt-signature"] == expected
    assert json.loads(body)["alert"]["alert_id"] == "a1" and abs(int(ts) - time.time()) < 5


def test_webhook_retries_with_backoff_then_counts_failure(monkeypatch):
    flaky = Hub(fail_first=2)
    try:
        n = WebhookNotifier([WebhookConfig(url=flaky.url, retries=3, timeout_s=2)])
        n.start()
        n.notify(alert())
        assert wait(lambda: n.stats["sent"] == 1, 10) and len(flaky.requests) == 3  # 2 failures + success
        n.stop()
    finally:
        flaky.close()
    dead = WebhookNotifier([WebhookConfig(url="http://127.0.0.1:9", retries=1, timeout_s=1)])
    dead.start()
    dead.notify(alert())
    assert wait(lambda: dead.stats["failed"] == 1, 10)
    dead.stop()
    with pytest.raises(ValueError, match="empty or missing"):
        WebhookNotifier([WebhookConfig(url="http://x.example", secret_env="SDT_MISSING_HOOK_SECRET")])


def test_webhook_queue_overflow_drops_instead_of_blocking(hub):
    n = WebhookNotifier([WebhookConfig(url=hub.url)], max_queue=2)  # worker not started: queue fills
    start = time.time()
    for _ in range(10):
        n.notify(alert())
    assert n.stats["dropped"] == 8 and time.time() - start < 1.0


def test_forwarder_batches_signs_and_authenticates(hub):
    secret = b"edge-secret-" + b"x" * 20
    f = Forwarder(hub.url, "sdtr_o1_secretvalue", batch_size=50, flush_s=0.05, secrets={"edge-1": secret})
    f.start()
    for i in range(120):
        f.submit({"sensor_id": "edge-1", "t": 1795000000.0 + i, "range_m": 100.0 + i, "azimuth_deg": 1.0, "elevation_deg": 1.0})
    f.submit({"sensor_id": "other", "t": 1795000000.0, "range_m": 1.0, "azimuth_deg": 1.0, "elevation_deg": 1.0})
    assert not f.submit("not a dict")
    assert wait(lambda: f.stats["forwarded"] == 121)
    f.stop()
    assert all(path == "/api/v1/ingest/detections" and h["x-api-key"] == "sdtr_o1_secretvalue" for path, h, _ in hub.requests)
    sent = [d for _, _, body in hub.requests for d in json.loads(body)]
    edge = [d for d in sent if d["sensor_id"] == "edge-1"]
    assert len(edge) == 120 and all(verify(secret, d) for d in edge)  # signed by the node, verifiable at the hub
    assert "sig" not in next(d for d in sent if d["sensor_id"] == "other")  # no secret => forwarded as is
    assert max(len(json.loads(b)) for _, _, b in hub.requests) <= 50


def test_forwarder_survives_hub_outage_with_bounded_memory_and_recovers():
    f = Forwarder("http://127.0.0.1:9", None, flush_s=0.05, max_queue=100, retries=0, timeout_s=0.5)
    for i in range(1000):  # not started: simulates a long outage
        f.submit({"sensor_id": "e", "t": float(i)})
    assert f.stats["dropped"] == 900 and len(f._q) == 100  # oldest shed, memory capped
    f.start()
    assert wait(lambda: f.stats["failed_batches"] >= 1, 5)
    f.stop(drain_s=0.2)
    good = Hub()
    try:
        g = Forwarder(good.url, None, flush_s=0.05)
        g.start()
        g.submit({"sensor_id": "e", "t": 1.0})
        assert wait(lambda: g.stats["forwarded"] == 1)
        g.stop()
    finally:
        good.close()


def test_forwarder_does_not_retry_auth_errors():
    class Deny(BaseHTTPRequestHandler):
        hits = 0

        def do_POST(self):  # noqa: N802
            Deny.hits += 1
            self.rfile.read(int(self.headers["content-length"]))
            self.send_response(401)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Deny)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        f = Forwarder(f"http://127.0.0.1:{srv.server_port}", "bad-key", flush_s=0.05, retries=4)
        f.start()
        f.submit({"sensor_id": "e", "t": 1.0})
        assert wait(lambda: f.stats["failed_batches"] == 1)
        f.stop()
        assert Deny.hits == 1  # a wrong key cannot succeed on retry: no hammering the hub
    finally:
        srv.shutdown()
