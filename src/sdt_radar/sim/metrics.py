"""Scoring of tracker output against simulation ground truth."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

from ..models import TrackOut


@dataclass
class Score
    class_known: int = 0
    class_correct: int = 0
    class_drone_vs_bird_wrong: int = 0
    matched_ids: set[str] = field(default_factory=set)
    unmatched_ids: set[str] = field(default_factory=set)
    _last_id: dict[str, str] = field(defa
    def rmse_horizontal_m(self) -> float:
        return float(np.sqrt(self.horiz_sq_err / self.matched)) if self.matched else float("nan")

    @property
    def rmse_vertical_m(self) -> float:
        return float(np.sqrt(self.vert_sq_err / self.matched)) if self.matched else float("nan")

    @property
    def class_accuracy(self) -> float:
        return self.class_correct / self.class_known if self.class_known else float("nan")

    @property
    def class_coverage(self) -> float:
        return self.class_known / self.matched if self.matched else float("nan")

    def summary(self) -> dict[str, float]:
        return {
            "detection_rate": self.detection_rate, "false_track_ids": float(self.false_track_ids),
            "false_tracks_per_eval": self.false_tracks_per_eval, "rmse_horizontal_m": self.rmse_horizontal_m,
            "rmse_vertical_m": self.rmse_vertical_m, "id_switches": float(self.id_switches),
            "class_accuracy": self.class_accuracy, "class_coverage": self.class_coverage,
            "drone_bird_confusions": float(self.class_drone_vs_bird_wrong),
        }


def evaluate_snapshot(score: Score, truth: list[tuple[str, str, np.ndarray]], tracks: list[TrackOut],
                      gate_m: float = 100.0) -> None:
    """Match confirmed tracks to truth (Hungarian on ENU position) and accumulate metrics.

    ``truth`` holds only targets that are expected to be tracked at this instant.
    """
    score.evals += 1
    confirmed = [t for t in tracks if t.status.value in ("confirmed", "coasting")]
    score.expected += len(truth)
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
        tr = confirmed[ti]
        matched_tracks.add(ti)
        score.matched += 1
        e = tp[ti] - gpos
        score.horiz_sq_err += float(e[0] ** 2 + e[1] ** 2)
        score.vert_sq_err += float(e[2] ** 2)
        score.matched_ids.add(tr.track_id)
        prev = score._last_id.get(tid)
        if prev is not None and prev != tr.track_id:
            score.id_switches += 1
        score._last_id[tid] = tr.track_id
        if tr.target_class.value != "unknown":
            score.class_known += 1
            ok = tr.target_class.value == kind
            score.class_correct += int(ok)
            if not ok and {tr.target_class.value, kind} == {"drone", "bird"}:
                score.class_drone_vs_bird_wrong += 1
    for i, tr in enumerate(confirmed):
        if i not in matched_tracks:
            score.unmatched_track_instants += 1
            score.unmatched_ids.add(tr.track_id)
