"""Turnaround profile: several lanes of camera-observed activity from the SAM detections the
pipeline already has (no extra model calls).

Lanes: aircraft on stand (SAM 'aircraft' box present), one lane per event in the event library
(equipment in that event's zone; only `loading` is validated on our footage), and ground staff
near the aircraft (count of SAM 'person' boxes). Every lane names its source and whether it is
validated, so the console can say so.
"""

from __future__ import annotations

import json
from pathlib import Path

from turnproof.events.candidates import aircraft_box_for, occupancy_series
from turnproof.events.milestones import merge_gaps, raw_cycles, smooth
from turnproof.perception.sam_parse import Det, iou
from turnproof.zones.aircraft_zones import overlap_ratio


def _intervals(
    samples: list[tuple[int, float, float]],
    tau: float,
    min_on: int,
    min_off: int,
    merge_gap: int,
    smooth_window: int,
) -> list[dict]:
    sm = smooth(samples, smooth_window)
    cycles = merge_gaps(raw_cycles(sm, tau, min_on, min_off, 1), merge_gap)
    last = samples[-1][0] if samples else 0
    return [
        {"start": c.start, "end": c.end if c.end is not None else last, "open": c.end is None,
         "present_at_clip_start": c.present_at_clip_start, "conf": round(c.conf, 3)}
        for c in cycles
    ]  # fmt: skip


def build_profile(
    *,
    aircraft: dict[int, list[Det]],
    vehicles: dict[int, list[Det]],
    persons: dict[int, list[Det]],
    cfg: dict,
    events: dict,
    view_zones: dict,
    fps: float,
    n_frames: int,
    speed: float | None,
    reference_start_utc: str | None,
    event_used: str,
    zone_used: str,
) -> dict:
    rules = cfg["rules"]
    step = max(1, round(fps / float(cfg.get("sampling", {}).get("logic_fps", 2))))
    frames = list(range(0, n_frames, step))

    def frames_for(real_s: float, floor: float = 2.0, cap: float = 12.0) -> int:
        v = max(floor, min(cap, real_s / (speed or 1.0)))
        return max(1, round(v * fps / step))

    min_on = frames_for(rules["docked_min_real_s"])
    min_off = frames_for(rules["undocked_min_real_s"])
    merge = frames_for(rules["merge_gap_real_s"], cap=24.0) * step
    sw = frames_for(rules.get("smooth_window_s", 1.0), floor=0.0) | 1
    tau = rules["docked_overlap_tau"]
    lanes: list[dict] = []

    # 1. aircraft on stand: a SAM aircraft box exists in the frame
    ac_series = [(f, 1.0 if aircraft.get(f) else 0.0, 0.95) for f in frames]
    lanes.append(
        {
            "key": "aircraft",
            "label": "Aircraft on stand",
            "source": "SAM 3.1 'aircraft'",
            "validated": True,
            "intervals": _intervals(ac_series, 0.5, min_on, min_off, merge, sw),
        }
    )

    # 2. one lane per event in the library (zones present in this camera view)
    for name, ev in events.items():
        zones = [z for z in ev.get("zones", []) if z in view_zones]
        if not zones:
            continue
        best_series, best_zone = None, None
        for z in zones:
            series = occupancy_series(vehicles, aircraft, view_zones, z, False, step=step)
            inside = sum(1 for _, ov, _ in series if ov >= tau)
            if best_series is None or inside > sum(1 for _, ov, _ in best_series if ov >= tau):
                best_series, best_zone = series, z
        if name == event_used:
            best_zone = zone_used
            best_series = occupancy_series(
                vehicles, aircraft, view_zones, zone_used, False, step=step
            )
        lanes.append(
            {
                "key": name,
                "label": ev.get("label", name),
                "source": f"SAM 3.1 'vehicle' in zone {best_zone}",
                "zone": best_zone,
                "validated": bool(ev.get("validated", False)),
                "primary": name == event_used,
                "intervals": _intervals(best_series or [], tau, min_on, min_off, merge, sw),
            }
        )

    # 3. ground staff near the aircraft: person boxes within the padded aircraft box
    counts: list[tuple[int, float, float]] = []
    series_counts: list[list[int]] = []
    for f in frames:
        ab = aircraft_box_for(f, aircraft)
        n = 0
        for d in persons.get(f, []):
            if ab is None:
                n += 1
                continue
            w, h = ab[2] - ab[0], ab[3] - ab[1]
            near = (ab[0] - 0.25 * w, ab[1] - 0.1 * h, ab[2] + 0.25 * w, ab[3] + 0.6 * h)
            if overlap_ratio(d.box, near) > 0 and iou(d.box, ab) < 0.5:
                n += 1
        counts.append((f, 1.0 if n else 0.0, min(1.0, n / 6)))
        series_counts.append([f, n])
    iv = _intervals(counts, 0.5, max(1, min_on // 2), max(1, min_off // 2), merge, sw)
    for it in iv:
        inside = [n for f, n in series_counts if it["start"] <= f <= it["end"]]
        it["max_count"] = max(inside) if inside else 0
        it["mean_count"] = round(sum(inside) / len(inside), 1) if inside else 0.0
    lanes.append(
        {
            "key": "persons",
            "label": "Ground staff near aircraft",
            "source": "SAM 3.1 'person' (count, blurred before display)",
            "validated": True,
            "intervals": iv,
            "series": series_counts,
        }
    )
    return {
        "fps": fps,
        "step": step,
        "n_frames": n_frames,
        "speed_factor": speed,
        "reference_start_utc": reference_start_utc,
        "lanes": lanes,
    }


def write_profile(run_dir: Path, profile: dict) -> Path:
    p = run_dir / "profile.json"
    p.write_text(json.dumps(profile))
    return p
