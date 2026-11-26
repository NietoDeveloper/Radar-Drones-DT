"""Async runtime: periodic pipeline ticks, UDP/TCP ingestion servers and the WebSocket hub."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from .api.hub import StreamHub
from .config import Settings
class Runtime:s
                log.exception("pipeline step failed")
            next_t += TICK_S
            await asyncio.sleep(max(0.0, next_t - time.monotonic