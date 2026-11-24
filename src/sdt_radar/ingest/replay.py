"""Replay recorded detections into a pipeline, deterministically (data-time) or paced (real-time)."""

from __future__ import annotations

import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from ..models import Detection

if TYPE_CHECKING:
    from ..pipeline import Pipeline, StepResult


def read_jsonl(path: str | Path) -> Iterator[Detection]:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield Detection.model_validate_json(line)


def replay(source: Iterable[Detection], pipeline: Pipeline, *, realtime: bool = False, speed: float = 1.0,
           step_s: float = 0.1) -> StepResult:
    """Feed detections (assumed time-ordered per sensor) and advance the pipeline in data time."""
    from ..pipeline import StepResult

    total = StepResult()
    first_t: float | None = None
    wall0 = time.monotonic()
    last_step = float("-inf")
    for det in source:
        if first_t is None:
            first_t = det.t
        if realtime:
            delay = (det.t - first_t) / speed - (time.monotonic() - wall0)
            if delay > 0:
                time.sleep(delay)
        pipeline.ingest(det)
        if det.t - last_step >= step_s:
            last_step = det.t
            total.merge(pipeline.step(det.t))
    total.merge(pipeline.step(last_step + 60.0, flush=True) if first_t is not None else StepResult())
    return total
