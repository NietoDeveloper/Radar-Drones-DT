"""Async runtime: periodic pipeline ticks, UDP/TCP ingestion servers and the WebSocket hub."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from .api.hub import StreamHub
from .config import Settings
class Runtime:s
        for srv in (self.udp, 
            if srv is not None:
                await srv.stop()

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
