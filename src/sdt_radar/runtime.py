"""Async runtime: periodic pipeline ticks, UDP/TCP ingestion servers and the WebSocket hub."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from .api.hub import StreamHub
from .config import Settings
from .ingest import TcpIngest, UdpIngest
from .notify import WebhookNotifier
from .pipeline import Pipeline

log = logging.getLogger("sdt_radar.runtime")

TICK_S = 0.05


class Runtime:
    def __init__(self, pipeline: Pipeline, settings: Settings, hub: StreamHub,
                 notifier: WebhookNotifier | None = None) -> None:
        self.pipeline, self.settings, self.hub, self.notifier = pipeline, settings, hub, notifier
        self._tasks: list[asyncio.Task] = []
        self.udp: UdpIngest | None = None
        self.tcp: TcpIngest | None = None

    async def start(self) -> None:
        cfg = self.settings.ingest
        loop = asyncio.get_running_loop()
        self.hub.bind_loop(loop)
        self.pipeline.add_alert_listener(self.hub.publish_alert_threadsafe)
        if self.notifier is not None:
            self.notifier.start()
            self.pipeline.add_alert_listener(self.notifier.notify)
        if cfg.udp_enabled and cfg.udp_port is not None:
            self.udp = UdpIngest(self.pipeline, cfg.host, cfg.udp_port)
            log.info("UDP ingest on %s:%d", cfg.host, await self.udp.start())
        if cfg.tcp_enabled and cfg.tcp_port is not None:
            self.tcp = TcpIngest(self.pipeline, cfg.host, cfg.tcp_port)
            log.info("TCP ingest on %s:%d", cfg.host, await self.tcp.start())
        self._tasks = [asyncio.create_task(self._tick(), name="sdt-tick"),
                       asyncio.create_task(self.hub.run(self.pipeline), name="sdt-hub")]
        if self.settings.storage.retention_days:
            self._tasks.append(asyncio.create_task(self._retention(), name="sdt-retention"))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t
        self._tasks.clear()
        for srv in (self.udp, self.tcp):
            if srv is not None:
                await srv.stop()
        if self.notifier is not None:
            await asyncio.to_thread(self.notifier.stop)

    async def _tick(self) -> None:
        next_t = time.monotonic()
        while True:
            try:
                self.pipeline.step(time.time())
            except Exception:  # keep the service alive; the error is visible in metrics and logs
                self.pipeline.stats["step_errors"] += 1
                log.exception("pipeline step failed")
            next_t += TICK_S
            await asyncio.sleep(max(0.0, next_t - time.monotonic()))

    async def _retention(self) -> None:
        """Hourly: delete stored points / closed records older than ``storage.retention_days``."""
        days = float(self.settings.storage.retention_days or 0)
        while True:
            try:
                n = await asyncio.to_thread(self.pipeline.store.prune, time.time() - days * 86400.0)
                self.pipeline.stats["retention_pruned"] += int(n)
                if self.pipeline.audit is not None and n:
                    self.pipeline.audit.append("retention_prune", detail={"points_deleted": int(n), "days": days})
            except Exception:
                log.exception("retention prune failed")
            await asyncio.sleep(3600.0)
