"""Raw-detection recorder (JSON lines). The audit trail and the input of deterministic replays."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TextIO

from ..models import Detection


class JsonlRecorder:
    def __init__(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._fh: TextIO = open(path, "a", buffering=1 << 16, encoding="utf-8")  # noqa: SIM115
        self._lock = threading.Lock()
        self.count = 0

    def write(self, det: Detection) -> None:
        line = det.model_dump_json(exclude_none=True)
        with self._lock:
            self._fh.write(line + "\n")
            self.count += 1

    def flush(self) -> None:
        with self._lock:
            self._fh.flush()

    def close(self) -> None:
        with self._lock:
            if not self._fh.closed:
                self._fh.close()
