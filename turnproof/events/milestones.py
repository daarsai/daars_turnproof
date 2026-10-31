"""Milestones from a loader track: docked/undocked with hysteresis.

Input: a list of (frame_index, overlap_ratio, confidence) sampled at logic_fps, in order.
Output: list of (name, frame_index, confidence) for loader_docked_start / loading_complete.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MilestoneHit:
    name: str
    frame_index: int
    confidence: float
    present_at_clip_start: bool = False  # docked run began on the very first sample


def detect(samples: list[tuple[int, float, float]], tau: float, min_docked: int, min_undocked: int):
    state = "UNDOCKED"
    run: list[tuple[int, float, float]] = []
    hits: list[MilestoneHit] = []
    first_idx = samples[0][0] if samples else None
    for idx, ov, c in samples:
        inside = ov >= tau
        if state == "UNDOCKED":
            run = run + [(idx, ov, c)] if inside else []
            if len(run) >= min_docked:
                state = "DOCKED"
                hits.append(
                    MilestoneHit(
                        "loader_docked_start", run[0][0], _mean(run), run[0][0] == first_idx
                    )
                )
                run = []
        else:  # DOCKED
            run = run + [(idx, ov, c)] if not inside else []
            if len(run) >= min_undocked:
                state = "UNDOCKED"
                hits.append(MilestoneHit("loading_complete", run[0][0], _mean(run)))
                run = []
    return hits


def _mean(run: list[tuple[int, float, float]]) -> float:
    return round(sum(c for _, _, c in run) / len(run), 3) if run else 0.0
