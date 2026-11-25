"""Storage port. Implementations: ``MemoryStore`` (tests/ephemeral), ``SqliteStore`` (edge / single node).

A TimescaleDB/PostgreSQL adapter implements the same protocol; the schema to start from is in
``docs/timescale_schema.sql`` (not yet implemented or tested in v1).
"""

from __future__ import annotations
