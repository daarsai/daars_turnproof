"""Milestones from a zone-occupancy series: docked/undocked with hysteresis, smoothing,
gap merging, and selection of the single longest loading cycle.

Input: list of (frame_index, overlap_ratio, confidence) in frame order (any fps).
Output: MilestoneHit list — at most one loader_docked_start and one loading_complete
(the longest cycle); all cycles are returned separately for the run summary.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class MilestoneHit:
    name: str
    frame_index: int
    confidence: float
    present_at_clip_start: bool = False  # docked run began on the very first sample


@dataclass(frozen=True)
class Cycle:
    start: int
    end: int | None  # None = still docked at clip end
    conf: float
    present_at_clip_start: bool


def smooth(samples: list[tuple[int, float, float]], window: int) -> list[tuple[int, float, float]]:
    """Rolling median of the overlap ratio (odd window); confidence is the rolling max."""
    if window <= 1 or len(samples) < window:
        return samples
    half = window // 2
    out = []
    for i in range(len(samples)):
        lo, hi = max(0, i - half), min(len(samples), i + half + 1)
        seg = samples[lo:hi]
        out.append((samples[i][0], median(s[1] for s in seg), max(s[2] for s in seg)))
    return out


def raw_cycles(
    samples: list[tuple[int, float, float]], tau: float, min_docked: int, min_undocked: int
) -> list[Cycle]:
    state = "UNDOCKED"
    run: list[tuple[int, float, float]] = []
    docked_conf: list[float] = []
    cycles: list[Cycle] = []
    start = 0
    first_idx = samples[0][0] if samples else None
    for idx, ov, c in samples:
        inside = ov >= tau
        if state == "UNDOCKED":
            run = run + [(idx, ov, c)] if inside else []
            if len(run) >= min_docked:
                state, start = "DOCKED", run[0][0]
                docked_conf = [r[2] for r in run]
                run = []
        else:
            if inside:
                docked_conf.append(c)
            run = run + [(idx, ov, c)] if not inside else []
            if len(run) >= min_undocked:
                cycles.append(Cycle(start, run[0][0], _mean(docked_conf), start == first_idx))
                state, run, docked_conf = "UNDOCKED", [], []
    if state == "DOCKED":
        cycles.append(Cycle(start, None, _mean(docked_conf), start == first_idx))
    return cycles


def merge_gaps(cycles: list[Cycle], max_gap: int) -> list[Cycle]:
    """Join cycles separated by an undocked gap shorter than max_gap frames (flicker)."""
    out: list[Cycle] = []
    for c in cycles:
        if out and out[-1].end is not None and c.start - out[-1].end < max_gap:
            p = out[-1]
            out[-1] = Cycle(
                p.start, c.end, round((p.conf + c.conf) / 2, 3), p.present_at_clip_start
            )
        else:
            out.append(c)
    return out


def detect(
    samples: list[tuple[int, float, float]],
    tau: float,
    min_docked: int,
    min_undocked: int,
    smooth_window: int = 1,
    merge_gap: int = 0,
) -> tuple[list[MilestoneHit], list[Cycle]]:
    """Return (milestones of the longest complete cycle, all cycles after merging)."""
    cycles = merge_gaps(
        raw_cycles(smooth(samples, smooth_window), tau, min_docked, min_undocked), merge_gap
    )
    complete = [c for c in cycles if c.end is not None]
    if complete:
        best = max(complete, key=lambda c: c.end - c.start)
    else:
        best = cycles[0] if cycles else None
    hits: list[MilestoneHit] = []
    if best:
        hits.append(
            MilestoneHit("loader_docked_start", best.start, best.conf, best.present_at_clip_start)
        )
        if best.end is not None:
            hits.append(MilestoneHit("loading_complete", best.end, best.conf))
    return hits, cycles


def _mean(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 3) if xs else 0.0
