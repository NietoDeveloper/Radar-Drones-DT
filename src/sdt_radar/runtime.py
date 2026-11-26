"""Async runtime: periodic pipeline ticks, UDP/TCP ingestion servers and the WebSocket hub."""

from __future__ import annotations

import asyncio
import contextlib
import logging