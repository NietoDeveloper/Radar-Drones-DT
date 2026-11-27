"""Scale benchmark: hundreds of simultaneous tracks through the full pipeline (data time)."""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from .sim import generate, run_scenario, swarm_scenario


def run(n_targets: int = 500, duration_s: float = 60.0, seed: int = 2) -> dict[str, Any]:
    scn = swarm_scenario(n_targets, seed, duration_s)
    t0 = time.perf_counter()
    dets = generate(scn)
    gen_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    pipe, score, _ = run_scenario(scn, detections=dets, step_s=0.5, eval_every_s=2.0, warmup_s=20.0, gate_m=250.0)
    wall_s = time.perf_counter() - t0
    step = np.array(pipe.step_ms)
    busy = step[step > 0.05]  # steps that actually processed a scan
    m = pipe.metrics()
    return {
        "targets": n_targets_duration_s": duration_s, "detections": len(dets),
        "live_tracks_end": sum(m["tracks_by_status"].values()), "generation_s": round(gen_s, 2),
        "pipeline_wall_s": round(wall_s, 2), "realtime_factor": round(duration_s / wall_s, 1),
        "step_ms_p50": round(float(np.percentile(busy, 50)), 2) if busy.size else None,
        "step_ms_p99": round(float(np.percentile(busy, 99)), 2) if busy.size else None,
        "step_ms_max": round(float(busy.max()), 2) if busy.size else None,
        **{k: (round(v, 3) if v == v else None) for k, v in score.summary().items()},
    }


def main() -> None:
    import json

    print(json.dumps(run(), indent=2))


if __name__ == "__main__":
    main()
