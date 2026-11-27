"""Edge-node forwarder: collect detections locally (UDP/TCP) and ship them to a central hub.

For distributed networks of cheap SDR / edge nodes. Detections are optionally signed per sensor (HMAC),
batched, sent over HTTPS with an operator API key, retried with back-off, and buffered in a bounded queue
that sheds the oldest data during long outages (counted, never unbounded memory).
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from typing import Any

from .ingest.net import MAX_DATAGRAM, MAX_LINE, iter_json_objects
from .security import sign

log = logging.getLogger("sdt_radar.forwarder")


class Forwarder:
    def __init__(self, hub_url: str, api_key: str | None, *, batch_size: int = 200, flush_s: float = 0.25,
                 max_queue: int = 50_000, secrets: dict[str, bytes] | None = None, timeout_s: float = 5.0,
                 retries: int = 4, cafile: str | None = None) -> None:
        self.url = hub_url.rstrip("/") + "/api/v1/ingest/detections"
        self.api_key, self.batch_size, self.flush_s = api_key, batch_size, flush_s
        self.secrets, self.timeout_s, self.retries = secrets or {}, timeout_s, retries
        # HTTPS to the hub verifies the certificate (system CAs, or a private CA via ``cafile``); never disabled.
        self._ssl = ssl.create_default_context(cafile=cafile) if hub_url.startswith("https://") else None
        self._q: deque[dict[str, Any]] = deque(maxlen=max_queue)
        self._cv = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.stats = {"queued": 0, "forwarded": 0, "rejected_by_hub": 0, "failed_batches": 0, "dropped": 0}

    def submit(self, obj: Any) -> bool:
        if not isinstance(obj, dict):
            return False
        sid = obj.get("sensor_id")
        secret = self.secrets.get(sid) if isinstance(sid, str) else None
        if secret is not None and "sig" not in obj:
            obj = {**obj, "sig": sign(secret, obj)}
        with self._cv:
            if len(self._q) == self._q.maxlen:
                self.stats["dropped"] += 1  # deque drops the oldest on append
            self._q.append(obj)
            self.stats["queued"] += 1
            self._cv.notify()
        return True

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="sdt-forwarder", daemon=True)
        self._thread.start()

    def stop(self, drain_s: float = 5.0) -> None:
        end = time.time() + drain_s
        while self._q and time.time() < end:
            time.sleep(0.05)
        self._stop.set()
        with self._cv:
            self._cv.notify_all()
        if self._thread:
            self._thread.join(timeout=drain_s)

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._cv:
                if not self._q:
                    self._cv.wait(self.flush_s)
                batch = [self._q.popleft() for _ in range(min(self.batch_size, len(self._q)))]
            if batch:
                self._send(batch)

    def _send(self, batch: list[dict[str, Any]]) -> None:
        body = json.dumps(batch, separators=(",", ":")).encode()
        headers = {"Content-Type": "application/json", **({"X-API-Key": self.api_key} if self.api_key else {})}
        for attempt in range(self.retries + 1):
            try:
                req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout_s, context=self._ssl) as r:  # noqa: S310 - operator-supplied hub
                    res = json.loads(r.read() or b"{}")
                self.stats["forwarded"] += int(res.get("accepted", 0))
                self.stats["rejected_by_hub"] += int(res.get("rejected", 0))
                return
            except urllib.error.HTTPError as exc:
                if exc.code in (400, 401, 403, 413, 422):  # retrying cannot help
                    log.error("hub refused the batch with HTTP %s", exc.code)
                    break
                log.warning("hub error %s (attempt %d)", exc.code, attempt + 1)
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                log.warning("hub unreachable: %s (attempt %d)", exc, attempt + 1)
            time.sleep(min(0.5 * 2**attempt, 8.0))
        self.stats["failed_batches"] += 1


class _Udp(asyncio.DatagramProtocol):
    def __init__(self, fwd: Forwarder) -> None:
        self.fwd = fwd

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if len(data) <= MAX_DATAGRAM:
            for o in iter_json_objects(data)[0]:
                self.fwd.submit(o)


async def serve_forward(fwd: Forwarder, host: str, udp_port: int | None, tcp_port: int | None) -> None:
    loop = asyncio.get_running_loop()
    fwd.start()
    servers: list[Any] = []
    if udp_port is not None:
        transport, _ = await loop.create_datagram_endpoint(lambda: _Udp(fwd), local_addr=(host, udp_port))
        servers.append(transport)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                line = await reader.readuntil(b"\n")
                for o in iter_json_objects(line)[0]:
                    fwd.submit(o)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionResetError):
            pass
        finally:
            writer.close()

    if tcp_port is not None:
        servers.append(await asyncio.start_server(handle, host, tcp_port, limit=MAX_LINE))
    try:
        await asyncio.Event().wait()
    finally:
        for s in servers:
            s.close()
        fwd.stop()


__all__ = ["Forwarder", "serve_forward"]
