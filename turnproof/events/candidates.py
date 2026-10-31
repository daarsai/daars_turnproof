"""From per-frame detections to milestones: equipment-agnostic.

Any 'vehicle' box (excluding the aircraft itself) that overlaps a hold zone >= tau counts as
loading equipment present at that hold. No identity tracking is needed.
"""

from __future__ import annotations

from turnproof.events.milestones import MilestoneHit, detect
from turnproof.perception.sam_parse import Det, iou, largest
from turnproof.zones.aircraft_zones import all_zones, overlap_ratio

Box = tuple[float, float, float, float]


def aircraft_box_for(frame: int, aircraft: dict[int, list[Det]]) -> Box | None:
    """Nearest earlier (or any) frame with an aircraft detection -> its largest box."""
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
    nose_left: bool = False,
    aircraft_iou_reject: float = 0.5,
) -> list[tuple[int, float, float]]:
    """(frame, max overlap ratio of any vehicle with the zone, confidence) per frame."""
    series: list[tuple[int, float, float]] = []
    for frame in sorted(vehicles):
        ab = aircraft_box_for(frame, aircraft)
        if ab is None:
            series.append((frame, 0.0, 0.0))
            continue
        zone = all_zones(ab, zones_cfg, nose_left)[zone_name]
        best_ov, best_c = 0.0, 0.0
        for d in vehicles[frame]:
            if iou(d.box, ab) >= aircraft_iou_reject:
                continue  # the aircraft mis-labelled as a vehicle
            ov = overlap_ratio(d.box, zone)
            if ov > best_ov:
                best_ov, best_c = ov, d.c or 0.0
        series.append((frame, best_ov, best_c))
    return series


def milestones_for_zone(
    vehicles: dict[int, list[Det]],
    aircraft: dict[int, list[Det]],
    cfg: dict,
    zone_name: str,
    nose_left: bool = False,
) -> list[MilestoneHit]:
    rules = cfg["rules"]
    series = occupancy_series(vehicles, aircraft, cfg["zones"], zone_name, nose_left)
    return detect(
        series,
        rules["docked_overlap_tau"],
        rules["docked_min_frames"],
        rules["undocked_min_frames"],
    )


def cycles(hits: list[MilestoneHit]) -> list[tuple[int, int]]:
    """(docked_start_frame, loading_complete_frame) pairs in order."""
    out, start = [], None
    for h in hits:
        if h.name == "loader_docked_start":
            start = h.frame_index
        elif h.name == "loading_complete" and start is not None:
            out.append((start, h.frame_index))
            start = None
    return out


def best_zone(
    vehicles: dict[int, list[Det]], aircraft: dict[int, list[Det]], cfg: dict, nose_left: bool
) -> tuple[str, list[MilestoneHit]]:
    """Pick the hold zone with the longest complete docked->complete stay (loading takes
    minutes; a vehicle driving past does not). Falls back to the zone with most hits."""
    results = {
        z: milestones_for_zone(vehicles, aircraft, cfg, z, nose_left)
        for z in cfg["zones"]
        if z.endswith("_hold")
    }
    longest = {z: max((b - a for a, b in cycles(h)), default=0) for z, h in results.items()}
    if any(longest.values()):
        z = max(longest, key=longest.get)
    elif results:
        z = max(results, key=lambda k: len(results[k]))
    else:
        z = next(iter(cfg["zones"]))
    return z, results.get(z, [])
