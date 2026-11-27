"""Outbound alert delivery: signed webhooks with bounded queue, retry and back-off.

Each delivery is ``POST <url>`` with a JSON body ``{"event": "alert", "alert": {...}}`` and headers
``X-SDT-Timestamp`` and ``X-SDT-Signature: sha256=<HMAC-SHA256(secret, timestamp + "." + body)>`` so the
receiver can authenticate the sender and reject replays. Delivery never blocks the tracking pipeline.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import queue
import threading
import time
import urllib.error
import urllib.request

from .config import WebhookConfig
from .models import AlertLevel, AlertOut

log = logging.getLogger("sdt_radar.notify")
_RANK = {AlertLevel.info: 0, AlertLevel.warning: 1, AlertLevel.critical: 2}


def signature(secret: bytes, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret, timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


class WebhookNotifier:
    def __init__(self, hooks: list[WebhookConfig], max_queue: int = 1000) -> None:
        self.hooks = hooks
        self._q: queue.Queue[tuple[WebhookConfig, bytes] | None] = queue.Queue(maxsize=max_queue)
        self._thread: threading.Thread | None = None
        self.stats = {"sent": 0, "failed": 0, "dropped": 0}
        self._secrets = {h.url: (os.environ.get(h.secret_env, "").encode() if h.secret_env else b"") for h in hooks}
        for h in hooks:
            if h.secret_env and not self._secrets[h.url]:
                raise ValueError(f"webhook {h.url}: environment variable {h.secret_env} is empty or missing")

    def start(self) -> None:
        if self._thread is None and self.hooks:
            self._thread = threading.Thread(target=self._run, name="sdt-webhooks", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        if self._thread is not None:
            self._q.put(None)
            self._thread.join(timeout=10)
            self._thread = None

    def notify(self, alert: AlertOut) -> None:
        body = json.dumps({"event": "alert", "alert": alert.model_dump(mode="json")}, separators=(",", ":")).encode()
        for h in self.hooks:
            if _RANK[alert.level] >= _RANK[h.min_level]:
                try:
                    self._q.put_nowait((h, body))
                except queue.Full:
                    self.stats["dropped"] += 1

    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                return
            hook, body = item
            for attempt in range(hook.retries + 1):
                if self._post(hook, body):
                    self.stats["sent"] += 1
                    break
                time.sleep(min(0.5 * 2**attempt, 8.0))
            else:
                self.stats["failed"] += 1

    def _post(self, hook: WebhookConfig, body: bytes) -> bool:
        ts = str(int(time.time()))
        headers = {"Content-Type": "application/json", "X-SDT-Event": "alert", "X-SDT-Timestamp": ts,
                   "User-Agent": "sdt-drone-radar/2"}
        secret = self._secrets[hook.url]
        if secret:
            headers["X-SDT-Signature"] = signature(secret, ts, body)
        try:
            req = urllib.request.Request(hook.url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=hook.timeout_s) as r:  # noqa: S310 - operator-configured URL
                return bool(200 <= r.status < 300)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            log.warning("webhook %s failed: %s", hook.url, exc)
            return False
