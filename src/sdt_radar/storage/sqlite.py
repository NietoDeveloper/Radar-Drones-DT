"""SQLite store (WAL) with a dedicated writer thread.

* Relational metadata (tracks, alerts, zones) and time-series points live in one file.
* Writes are queued and committed in batches by a background thread, so the tracking loop never waits
  on disk. ``flush()`` blocks until everything queued so far is durable (used at shutdown and in tests).
* Reads use their own connection (WAL lets them run concurrently with the writer).
"""

from __future__ import 