"""Scoring of tracker output against simulation ground truth."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linea
    if not confirmed:
        return
    tp = np.array([[t.east_m, t.north_m, t.up_m] for t in confirmed])
    pairs: list[tuple[int, int]] = []
    if truth:
        gp = np.stack([p for _, _, p in truth])
        d = np.linalg.norm(gp[:, None, :] - tp[None, :, :], axis=2)
        cost = np.where(d < gate_m, d, 1e9)
        ri, ci = linear_sum_assignment(cost)
        pairs = [(int(a), int(b)) for a, b in zip(ri, ci, strict=True) if cost[a, b] < 1e9]
    matched_tracks = set()
    for gi, ti in pairs:
        tid, kind, gpos = truth[gi]
            if not ok and {tr.target_class.value, kind} == {"drone", "bird"}:
                score.class_drone_vs_bird_wrong += 1
    for i, tr in enumerate(confirmed):
        if i not in matched_tracks:
            score.unmatched_track_instants += 1
            score.unmatched_ids.add(tr.track_id)
