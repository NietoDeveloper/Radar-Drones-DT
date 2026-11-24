"""WebSocket fan-out: periodic track snapshots + immediate alert events, with per-client filters.

Slow clients never slow the pipeline: each subscriber has a bounded queue; when it is full the
*oldest* message is dropped (the next snapshot supersedes it anyway).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..models import AlertOut, TargetClass, TrackOut

if TYPE_CHECKING:
    from ..pipeline import Pipeline

PROTOCOL_VERSION = 1


@dataclass(eq=False)  # identity semantics: subscribers live in a set
class Subscriber:
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=lambda: asyncio.Queue(maxsize=16))
    classes: set[TargetClass] | None = None
    min_confidence: float = 0.0
    include_tentative: bool = False
    dropped: int = 0

    def accepts(self, t: TrackOut) -> bool:
        if self.classes is not None and t.target_class not in self.classes:
            return False
        return t.confidence >= self.min_confidence

    def push(self, msg: dict[str, Any]) -> None:
        if self.queue.full():
            try:
                self.queue.get_nowait()
                self.dropped += 1
            except asyncio.QueueEmpty:  # pragma: no cover
                pass
        self.queue.put_nowait(msg)


class StreamHub:
    def __init__(self, snapshot_hz: float) -> None:
        self.period = 1.0 / snapshot_hz
        self.snapshot_hz = snapshot_hz
        self.subscribers: set[Subscriber] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self.published = 0

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def add(self) -> Subscriber:
        s = Subscriber()
        self.subscribers.add(s)
        s.push({"type": "hello", "protocol": PROTOCOL_VERSION, "snapshot_hz": self.snapshot_hz,
                "server_time": time.time()})
        return s

    def remove(self, s: Subscriber) -> None:
        self.subscribers.discard(s)

    def publish_alert_threadsafe(self, alert: AlertOut) -> None:
        if self._loop is None:
            return
        msg = {"type": "alert", "alert": alert.model_dump(mode="json")}
        self._loop.call_soon_threadsafe(self._fan_out, msg)

    def _fan_out(self, msg: dict[str, Any]) -> None:
        for s in list(self.subscribers):
            s.push(msg)

    async def run(self, pipeline: Pipeline) -> None:
        next_t = time.monotonic()
        while True:
            if self.subscribers:
                self.publish_snapshot(pipeline)
            next_t += self.period
            await asyncio.sleep(max(0.0, next_t - time.monotonic()))

    def publish_snapshot(self, pipeline: Pipeline) -> None:
        now = time.time()
        tracks = pipeline.snapshot(now, include_tentative=any(s.include_tentative for s in self.subscribers))
        dumped = {t.track_id: t.model_dump(mode="json") for t in tracks}
        for s in list(self.subscribers):
            sel = [dumped[t.track_id] for t in tracks
                   if s.accepts(t) and (s.include_tentative or t.status.value != "tentative")]
            s.push({"type": "snapshot", "server_time": now, "count": len(sel), "tracks": sel})
        self.published += 1
