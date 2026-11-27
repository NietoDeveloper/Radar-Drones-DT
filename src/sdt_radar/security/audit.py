"""Tamper-evident audit log: an append-only JSON-lines file where every record hashes the previous one.

``hash = SHA-256(prev_hash || canonical(record without hash))``. Editing, deleting or re-ordering any line
breaks the chain and ``AuditLog.verify`` reports the first bad line. Truncating the *tail* cannot be
detected from the file alone: anchor ``head()`` (sequence + hash) somewhere external (``GET
/api/v1/audit/head``) on a schedule if that matters.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GENESIS = "0" * 64


def _h(prev: str, rec: dict[str, Any]) -> str:
    body = json.dumps(rec, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256((prev + body).encode()).hexdigest()


@dataclass
class AuditReport:
    ok: bool
    records: int
    error_line: int | None = None
    error: str | None = None


class AuditLog:
    def __init__(self, path: str | Path, max_per_min: int = 30) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._max_per_min = max_per_min
        self._recent: dict[str, deque[float]] = defaultdict(deque)
        self.suppressed = 0
        self._seq, self._prev = 0, GENESIS
        rep = self.verify(self.path)
        if not rep.ok:
            raise ValueError(f"audit log {self.path} failed verification at line {rep.error_line}: {rep.error}")
        if rep.records:
            last = self.path.read_text(encoding="utf-8").strip().splitlines()[-1]
            rec = json.loads(last)
            self._seq, self._prev = rec["seq"], rec["hash"]

    def head(self) -> dict[str, Any]:
        with self._lock:
            return {"seq": self._seq, "hash": self._prev}

    def append(self, action: str, actor: str = "-", role: str | None = None, ip: str | None = None,
               detail: dict[str, Any] | None = None, ts: float | None = None) -> bool:
        """Append a record. Floods of the same action are capped per minute (returns False when suppressed)."""
        now = time.time() if ts is None else ts
        with self._lock:
            q = self._recent[action]
            while q and q[0] < now - 60.0:
                q.popleft()
            if len(q) >= self._max_per_min:
                self.suppressed += 1
                return False
            q.append(now)
            self._seq += 1
            rec: dict[str, Any] = {"seq": self._seq, "ts": round(now, 3), "action": action, "actor": actor, "role": role,
                   "ip": ip, "detail": detail or {}, "prev": self._prev}
            rec["hash"] = _h(self._prev, rec)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n")
                fh.flush()
            self._prev = rec["hash"]
            return True

    def tail(self, n: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").strip().splitlines()[-n:] if self.path.exists() else []
        return [json.loads(x) for x in lines if x]

    @staticmethod
    def verify(path: str | Path) -> AuditReport:
        p = Path(path)
        if not p.exists():
            return AuditReport(True, 0)
        prev, seq = GENESIS, 0
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                claimed = rec.pop("hash")
            except (ValueError, KeyError):
                return AuditReport(False, seq, i, "malformed record")
            if rec.get("prev") != prev:
                return AuditReport(False, seq, i, "chain broken (prev hash mismatch)")
            if rec.get("seq") != seq + 1:
                return AuditReport(False, seq, i, "sequence gap")
            if _h(prev, rec) != claimed:
                return AuditReport(False, seq, i, "record altered (hash mismatch)")
            prev, seq = claimed, seq + 1
        return AuditReport(True, seq)
