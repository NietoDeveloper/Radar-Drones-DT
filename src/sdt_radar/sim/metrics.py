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
        d = np.linalg.norm(gp[:, None, :] - tp[None,= {"drone", "bird"}:
                score.class_drone_vs_bird_wrong += 1
    for i, tr in enumerate(confirmed):
        if i not in matched_tracks:
            score.unmatched_track_instants += 1
            score.unmatched_ids.add(tr.track_id)
