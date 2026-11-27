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
        self._q.put(("zone_del", (zo
        if target_class is not None:
            sql += " AND target_class = ?"
            args.append(target_class.value)
        if since is not None:
            sql += " AND last_seen >= ?"
            args.append(since)
        sql += " ORDER BY last_seen DESC LIMIT ?"
        args.append(limit)
        return [TrackOut.model_validate_json(r[0]) for r in self._query(sql, tuple(args))]

    def history(self, track_id: str, since: float | None = None, until: float | None = None,
                limit: int = 5000) -> list[TrackPoint]:
        sql, args = "SELECT payload FROM points WHERE track_id = ?", [track_id]  # type: tuple[str, list[Any]]
        if since is not None:
            sql += " AND t >= ?"
            args.append(since)
        if until is not None:
            sql += " AND t <= ?"
            args.append(until)
        sql += " ORDER BY t ASC LIMIT ?"
        args.append(limit)
        return [TrackPoint.model_validate_json(r[0]) for r in self._query(sql, tuple(args))]

    def list_alerts(self, active_only: bool = False, since: float | None = None, limit: int = 1000) -> list[AlertOut]:
        sql, args = "SELECT payload FROM alerts WHERE 1=1", []  # type: tuple[str, list[Any]]
        if active_only:
            sql += " AND state = 'open'"
        if since is not None:
            sql += " AND updated_at >= ?"
            args.append(since)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        args.append(limit)
        return [AlertOut.model_validate_json(r[0]) for r in self._query(sql, tuple(args))]

    def list_zones(self) -> list[Zone]:
        return [Zone.model_validate_json(r[0]) for r in self._query("SELECT payload FROM zones")]

    # ---------------------------------------------------------------------------- writer thread
    def _writer(self) -> None:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA synchronous=NORMAL")
        pending = 0
        last_commit = time.monotonic()
        barriers: list[threading.Event] = []
        stop = False
        while not stop:
            try:
                item = self._q.get(timeout=self.commit_interval_s)
            except queue.Empty:
                item = None
            if item is _STOP:
                stop = True
            elif item is not None:
                kind, data = item
                try:
                    pending += self._apply(conn, kind, data, barriers)
                except sqlite3.Error:
                    self.errors += 1
            due = time.monotonic() - last_commit >= self.commit_interval_s
            if pending and (stop or due or pending >= self.batch_max or barriers):
                conn.commit()
                pending, last_commit = 0, time.monotonic()
            if barriers and not pending:
                for b in barriers:
                    b.set()
                barriers.clear()
        conn.commit()
        for b in barriers:
            b.set()
        conn.close()

    @staticmethod
    def _apply(conn: sqlite3.Connection, kind: str, data: Any, barriers: list[threading.Event]) -> int:
        if kind == "track":
            conn.execute("INSERT OR REPLACE INTO tracks VALUES (?,?,?,?,?,?,?,?,?)", data)
        elif kind == "points":
            conn.executemany("INSERT INTO points VALUES (?,?,?)", data)
            return len(data)
        elif kind == "alert":
            conn.execute("INSERT OR REPLACE INTO alerts VALUES (?,?,?,?)", data)
        elif kind == "zone":
            conn.execute("INSERT OR REPLACE INTO zones VALUES (?,?)", data)
        elif kind == "zone_del":
            conn.execute("DELETE FROM zones WHERE id = ?", data)
        elif kind == "barrier":
            barriers.append(data)
            return 0
        return 1
