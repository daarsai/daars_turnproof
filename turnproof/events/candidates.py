"""From per-frame detections to milestones: equipment-agnostic.

Any 'vehicle' box (excluding the aircraft itself) that overlaps a hold zone >= tau counts as
loading equipment present at that hold. No identity tracking is needed. The occupancy series
is sampled at logic_fps and smoothed; thresholds are given in SECONDS of video in config and
converted to frames here.
"""

from __future__ import annotations

from turnproof.events.milestones import Cycle, MilestoneHit, detect
from turnproof.perception.sam_parse import Det, iou, largest
from turnproof.zones.aircraft_zones import all_zones, overlap_ratio

Box = tuple[float, float, float, float]


def aircraft_box_for(frame: int, aircraft: dict[int, list[Det]]) -> Box | None:
    if not aircraft:
        return None
    keys = sorted(aircraft)
    best = max([k for k in keys if k <= frame], default=keys[0])
    d = largest(aircraft[best])
    return d.box if d else None


def occupancy_series(
    vehicles: dict[int, list[Det]],
    aircraft: dict[int, list[Det]],
    zones_cfg: dict,
    zone_name: str,
    nose_right: bool = False,
    aircraft_iou_reject: float = 0.5,
    step: int = 1,
) -> list[tuple[int, float, float]]:
    """(frame, max overlap ratio of any vehicle with the zone, that vehicle's confidence)."""
    series: list[tuple[int, float, float]] = []
    for frame in sorted(vehicles):
        if frame % step:
            continue
        ab = aircraft_box_for(frame, aircraft)
        if ab is None:
            series.append((frame, 0.0, 0.0))
            continue
        zone = all_zones(ab, zones_cfg, nose_right)[zone_name]
        best_ov, best_c = 0.0, 0.0
        for d in vehicles[frame]:
            if iou(d.box, ab) >= aircraft_iou_reject:
                continue
            ov = overlap_ratio(d.box, zone)
            if ov > best_ov:
                best_ov, best_c = ov, d.c or 0.0
        series.append((frame, best_ov, best_c))
    return series


def _video_s(real_s: float, speed: float | None, floor: float, cap: float) -> float:
    """Real-world seconds -> video seconds, clamped. Unknown speed: treat as real time."""
    v = real_s / (speed or 1.0)
    return max(floor, min(cap, v))


def _frames(seconds: float, fps: float, step: int) -> int:
    return max(1, round(seconds * fps / step))


def milestones_for_zone(
    vehicles: dict[int, list[Det]],
    aircraft: dict[int, list[Det]],
    cfg: dict,
    zone_name: str,
    fps: float,
    nose_right: bool = False,
    speed: float | None = None,
) -> tuple[list[MilestoneHit], list[Cycle]]:
    rules = cfg["rules"]
    logic_fps = float(cfg.get("sampling", {}).get("logic_fps", 2))
    step = max(1, round(fps / logic_fps))
    floor, cap = rules.get("floor_video_s", 2.0), rules.get("cap_video_s", 12.0)
    series = occupancy_series(vehicles, aircraft, cfg["zones"], zone_name, nose_right, step=step)
    return detect(
        series,
        rules["docked_overlap_tau"],
        _frames(_video_s(rules["docked_min_real_s"], speed, floor, cap), fps, step),
        _frames(_video_s(rules["undocked_min_real_s"], speed, floor, cap), fps, step),
        smooth_window=_frames(rules.get("smooth_window_s", 1.0), fps, step) | 1,
        merge_gap=_frames(_video_s(rules["merge_gap_real_s"], speed, floor, cap * 2), fps, step),
        end_floor=_frames(floor, fps, step),
    )


def best_zone(
    vehicles: dict[int, list[Det]],
    aircraft: dict[int, list[Det]],
    cfg: dict,
    fps: float,
    nose_right: bool = False,
    zones_enabled: list[str] | None = None,
    speed: float | None = None,
) -> tuple[str, list[MilestoneHit], dict[str, list[Cycle]]]:
    """Pick the hold zone with the longest complete docked->complete stay."""
    names = [z for z in cfg["zones"] if z.endswith("_hold")]
    if zones_enabled:
        names = [z for z in names if z in zones_enabled]
    results = {
        z: milestones_for_zone(vehicles, aircraft, cfg, z, fps, nose_right, speed) for z in names
    }
    all_cycles = {z: r[1] for z, r in results.items()}

    def longest(z: str) -> int:
        return max((c.end - c.start for c in all_cycles[z] if c.end is not None), default=0)

    if names and any(longest(z) for z in names):
        z = max(names, key=longest)
    elif names:
        z = max(names, key=lambda k: len(all_cycles[k]))
    else:
        z = next(iter(cfg["zones"]))
    return z, results.get(z, ([], []))[0], all_cycles
