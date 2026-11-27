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
import time
from pathlib import Path
from typing import Any

from ..models import AlertOut, TargetClass, TrackOut, TrackPoint, TrackStatus, Zone

_SCHEMA = """T EXISTS zones (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
"""
        self.commit_interval_s = commit_interval_s
        self.batch_max = batch_max
        self._q: queue.SimpleQueue[Any] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._read: sqlite3.Connection | None = None
        self._rlock = threading.Lock()
        self.errors = 0

    # ------------------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._thread is not None:
            return
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        init = sqlite3.connect(self.path)
        init.execute("PRAGMA journal_mode=WAL")
        init.executescript(_SCHEMA)
        init.commit()
        init.close()
        self._read = sqlite3.connect(self.path, check_same_thread=False)
        self._thread = threading.Thread(target=self._writer, name="sdt-store-writer", daemon=True)
        self._thread.start()

    def close(self) -> None:
        if self._thread is None:
            return
        self._q.put(_STOP)
        self._thread.join(timeout=10)
        self._thread = None
        if self._read is not None:
            self._read.close()
            self._read = None

    def flush(self, timeout: float = 5.0) -> None:
        if self._thread is None:
            return
        ev = threading.Event()
        self._q.put(("barrier", ev))
        ev.wait(timeout)

    # ----------------------------------------------------------------------------------- writes
    def write_track(self, track: TrackOut) -> None:
        self._q.put(("track", (track.track_id, track.seq, track.status.value, track.target_class.value,
                               track.class_confidence, track.confidence, track.first_seen, track.last_seen,
                               track.model_dump_json())))

    def write_points(self, track_id: str, points: list[TrackPoint]) -> None:
        if points:
            self._q.put(("points", [(track_id, p.t, p.model_dump_json()) for p in points]))

    def write_alert(self, alert: AlertOut) -> None:
        self._q.put(("alert", (alert.alert_id, alert.state, alert.updated_at, alert.model_dump_json())))

    def put_zone(self, zone: Zone) -> None:
        self._q.put(("zone", (zone.id, zone.model_dump_json())))

    def delete_zone(self, zone_id: str) -> None:
        self._q.put(("zone_del", (zone_id,)))

    def prune(self, older_than: float) -> int:
        self.flush()
        conn = sqlite3.connect(self.path)
        try:
            n = conn.execute("DELETE FROM points WHERE t < ?", (older_than,)).rowcount
            conn.execute("DELETE FROM tracks WHERE last_seen < ? AND status = 'lost'", (older_than,))
            conn.execute("DELETE FROM alerts WHERE updated_at < ? AND state = 'closed'", (older_than,))
            conn.commit()
            return int(n)
        finally:
            conn.close()

    # ------------------------------------------------------------------------------------ reads
    def _query(self, sql: str, args: tuple = ()) -> list[tuple]:
        assert self._read is not None, "store not started"
        with self._rlock:
            return self._read.execute(sql, args).fetchall()

    def get_track(self, track_id: str) -> TrackOut | None:
        rows = self._query("SELECT payload FROM tracks WHERE track_id = ?", (track_id,))
        return TrackOut.model_validate_json(rows[0][0]) if rows else None

    def list_tracks(self, status: TrackStatus | None = None, target_class: TargetClass | None = None,
                    since: float | None = None, limit: int = 1000) -> list[TrackOut]:
        sql, args = "SELECT payload FROM tracks WHERE 1=1", []  # type: tuple[str, list[Any]]
        if status is not None:
            sql += " AND status = ?"
            args.append(status.value)
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
