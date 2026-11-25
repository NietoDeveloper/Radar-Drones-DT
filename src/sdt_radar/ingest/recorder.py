"""Raw-detection recorder (JSON lines). The audit trail and the input of deterministic replays."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TextIO

from ..models import Detection

            self._fh.flush()

    def close(self) -> None:
        with self._lock:
            if not self._fh.closed:
                self._fh.close()
