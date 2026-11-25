"""Storage port. Implementations: ``MemoryStore`` (tests/ephemeral), ``SqliteStore`` (edge / single node).

A TimescaleDB/PostgreSQL adapter implements the same protocol; the schema to start from is in
``docs/timescale_schema.sql`` (not yet implemented or tested in v1).
"""

from __future__ import annotations

from typing import Protocol

from ..models import AlertOut, TargetClass, TrackOut, TrackPoint, TrackStatus, Zone
-> None: ...
    def prune(self, older_than: float) -> int: ...
