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
    departure_at_clip_end: bool = False  # clip ended before the full undocked threshold


@dataclass(frozen=True)
class Cycle:
    start: int
    end: int | None  # None = still docked at clip end
    conf: float
    present_at_clip_start: bool
    departure_at_clip_end: bool = False  # undocked run was cut short by the end of the clip


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
    samples: list[tuple[int, float, float]],
    tau: float,
    min_docked: int,
    min_undocked: int,
    end_floor: int = 1,
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
        if run and len(run) >= end_floor:
            # Departure observed, but the clip ended before the full undocked threshold.
            cycles.append(Cycle(start, run[0][0], _mean(docked_conf), start == first_idx, True))
        else:
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
    end_floor: int = 1,
) -> tuple[list[MilestoneHit], list[Cycle]]:
    """Return (milestones of the longest complete cycle, all cycles after merging).

    min_docked / min_undocked / end_floor are counts of SAMPLES; merge_gap is in FRAME units
    (the same units as sample[0]), because cycle start/end are frame indices.
    """
    sm = smooth(samples, smooth_window)
    cycles = merge_gaps(raw_cycles(sm, tau, min_docked, min_undocked, end_floor), merge_gap)
    # Leading-edge rule: if equipment was detected (even flickering) from near the start and the
    # first solid cycle begins within merge_gap of that, the cycle began at the first detection.
    first_inside = next((idx for idx, ov, _ in sm if ov >= tau), None)
    if cycles and first_inside is not None and 0 < cycles[0].start - first_inside < merge_gap:
        c0 = cycles[0]
        cycles[0] = Cycle(
            first_inside, c0.end, c0.conf, first_inside == sm[0][0], c0.departure_at_clip_end
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
            hits.append(
                MilestoneHit(
                    "loading_complete", best.end, best.conf, False, best.departure_at_clip_end
                )
            )
    return hits, cycles


def _mean(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 3) if xs else 0.0
