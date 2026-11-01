"""Estimate a clip's time-lapse factor from vehicle motion in cached SAM detections.

Method: for consecutive frames, match each vehicle box to the nearest similar-size box in the
next frame; convert pixel speed to metres using the aircraft box length (an assumed fuselage
length for the aircraft class); take the 98th-percentile video-time speed and divide by a
plausible real apron driving speed (default 4 m/s ~ 15 km/h). Rough (+/-50%), but measured.

Usage:
  python scripts/estimate_speed.py data/cache/sam/vehicle_<hash>.txt data/cache/sam/aircraft_<hash>.txt \
      --fps 25 --aircraft-length-m 37.6 [--real-speed 4.0]
"""

from __future__ import annotations

import argparse
import statistics
import sys
from itertools import pairwise
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from turnproof.perception.sam_parse import iou, largest, parse


def estimate(vehicle_txt: Path, aircraft_txt: Path, fps: float, ac_len_m: float, real: float):
    vehicles, aircraft = parse(vehicle_txt.read_text()), parse(aircraft_txt.read_text())
    ab = largest(aircraft[min(aircraft)]).box
    m_per_px = ac_len_m / max(ab[2] - ab[0], ab[3] - ab[1])
    frames = sorted(vehicles)
    speeds: list[float] = []
    for f0, f1 in pairwise(frames):
        if f1 - f0 != 1:
            continue
        for d in vehicles[f0]:
            if iou(d.box, ab) > 0.5 or d.area < 400:
                continue
            c0 = ((d.x1 + d.x2) / 2, (d.y1 + d.y2) / 2)
            best = None
            for e in vehicles[f1]:
                if iou(e.box, ab) > 0.5 or e.area < 400 or not (0.6 < e.area / d.area < 1.6):
                    continue
                c1 = ((e.x1 + e.x2) / 2, (e.y1 + e.y2) / 2)
                dist = ((c1[0] - c0[0]) ** 2 + (c1[1] - c0[1]) ** 2) ** 0.5
                best = dist if best is None or dist < best else best
            if best is not None and best < 0.8 * max(d.x2 - d.x1, d.y2 - d.y1):
                speeds.append(best * m_per_px * fps)
    speeds.sort()
    top = speeds[int(len(speeds) * 0.98) :]
    p98 = statistics.median(top) if top else 0.0
    return {"matched_pairs": len(speeds), "p98_video_speed_mps": round(p98, 1),
            "assumed_real_speed_mps": real, "estimated_speed_factor": round(p98 / real, 1) if real else None}  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("vehicle_txt")
    ap.add_argument("aircraft_txt")
    ap.add_argument("--fps", type=float, default=25.0)
    ap.add_argument("--aircraft-length-m", type=float, default=37.6, help="A320-class default")
    ap.add_argument("--real-speed", type=float, default=4.0, help="assumed apron speed, m/s")
    a = ap.parse_args()
    r = estimate(
        Path(a.vehicle_txt), Path(a.aircraft_txt), a.fps, a.aircraft_length_m, a.real_speed
    )
    for k, v in r.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
