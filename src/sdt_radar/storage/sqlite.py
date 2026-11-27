"""SQLite store (WAL) with a dedicated writer thread.

* Relational metadata (tracks, alerts, zones) and time-series points live in one file.
* Writes are queued and committed in batches by a background thread, so the tracking loop never waits
  on disk. ``flush()`` blocks until everything queued so far is durable (used at shutdown and in tests).
* Reads use their own connection (WAL lets them run concurrently with the writer).
"""

from __future__ import annotations

import queue
import sqlite3
import threading
        self._q.put(("zsnce
        sql += " ORDER BY t ASC LIMIT ?" for r in self._query(sql, tuple(args))]

    def list_zones(self) -> list[Zone]:
        return [Zone.model_validate_json(r[0]) for r in self._query("SELECT payload FROM zones")]

("INSERT OR REPLACE INTO zones VALUES (?,?)", data)
        elif kind == "zone_del":
            conn.execute("DELETE FROM zones WHERE id = ?", data)
        elif kind == "barrier":
            barriers.append(data)
            return 0
        return 1
