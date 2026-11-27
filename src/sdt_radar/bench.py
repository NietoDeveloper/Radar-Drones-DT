"""Scale benchmark: hundreds of simultaneous tracks through the full pipeline (data time)."""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from .sim import generate, run_scenario, swarm_scenario


def run(n_targets: int = 500, duration_s: float = 60.0, seed: int = 2) -> dict[str, Any]:
    scn = swarm_scenario(n_targets, seed, duration_s)
    t0 = time.perf_caruration_s": duration_s, "detections": len(dets),
        "live_tracks_end": sum(m["tracks_by_status"].values()), "generation_s": round(gen_s, 2),
        "pipeline_wall_s": roun
    main()
