"""Visual evidence for the console: boxes drawn on redacted display frames, plus the
occupancy series the milestone rule was computed from.

Overlays are DISPLAY artefacts only. They are written as separate files
(display/<id>_overlay.png) so the hashed redacted frames (display/<id>.png) never change.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2

from turnproof.events.candidates import aircraft_box_for
from turnproof.perception.sam_parse import Det, iou
from turnproof.zones.aircraft_zones import all_zones, overlap_ratio

Box = tuple[float, float, float, float]

# BGR colours (DAARS palette: navy, orange; green for equipment, grey for persons)
NAVY = (69, 37, 11)
ORANGE = (29, 107, 242)
GREEN = (96, 174, 39)
GREY = (160, 160, 160)
WHITE = (255, 255, 255)


def _rect(img, box: Box, colour, thick: int = 2, dashed: bool = False) -> None:
    x1, y1, x2, y2 = (round(v) for v in box)
    if not dashed:
        cv2.rectangle(img, (x1, y1), (x2, y2), colour, thick)
        return
    step = 16
    for x in range(x1, x2, step):
        cv2.line(img, (x, y1), (min(x + step // 2, x2), y1), colour, thick)
        cv2.line(img, (x, y2), (min(x + step // 2, x2), y2), colour, thick)
    for y in range(y1, y2, step):
        cv2.line(img, (x1, y), (x1, min(y + step // 2, y2)), colour, thick)
        cv2.line(img, (x2, y), (x2, min(y + step // 2, y2)), colour, thick)


def _label(img, text: str, x: int, y: int, colour, scale: float = 0.62) -> None:
    """Filled tag with its top-left corner at (x, y); kept inside the image."""
    font, thick = cv2.FONT_HERSHEY_SIMPLEX, 2
    (tw, th), _ = cv2.getTextSize(text, font, scale, thick)
    h, w = img.shape[:2]
    x = max(0, min(x, w - tw - 10))
    y = max(0, min(y, h - th - 10))
    cv2.rectangle(img, (x, y), (x + tw + 10, y + th + 10), colour, -1)
    cv2.putText(img, text, (x + 5, y + th + 4), font, scale, WHITE, thick, cv2.LINE_AA)


def _fill(img, box: Box, colour, alpha: float) -> None:
    x1, y1, x2, y2 = (round(v) for v in box)
    h, w = img.shape[:2]
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return
    roi = img[y1:y2, x1:x2]
    tint = roi.copy()
    tint[:] = colour
    cv2.addWeighted(tint, alpha, roi, 1 - alpha, 0, roi)


def draw_overlay(
    display_png: Path,
    out_png: Path,
    aircraft_box: Box | None,
    zones: dict[str, Box],
    vehicles: list[Det],
    active_zone: str | None,
    tau: float,
    aircraft_iou_reject: float = 0.5,
) -> Path | None:
    """Aircraft box (navy, dashed), hold zones (orange, the active one tinted), vehicles:
    green + label when overlapping the active zone >= tau, thin grey box otherwise.
    Returns None if the display frame is missing."""
    img = cv2.imread(str(display_png))
    if img is None:
        return None
    # boxes first, labels last so no outline runs through a label
    if aircraft_box:
        _rect(img, aircraft_box, NAVY, 2, dashed=True)
    for name, z in zones.items():
        active = name == active_zone
        if active:
            _fill(img, z, ORANGE, 0.14)
        _rect(img, z, ORANGE, 3 if active else 1, dashed=not active)
    n_in, best_c = 0, 0.0
    for d in vehicles:
        if aircraft_box and iou(d.box, aircraft_box) >= aircraft_iou_reject:
            continue  # the aircraft itself, mislabelled as a vehicle
        ov = overlap_ratio(d.box, zones[active_zone]) if active_zone in zones else 0.0
        if ov >= tau:
            n_in += 1
            best_c = max(best_c, d.c or 0.0)
            _rect(img, d.box, GREEN, 3)
        else:
            _rect(img, d.box, GREY, 1)
    if aircraft_box:
        _label(img, "aircraft  SAM 3.1", int(aircraft_box[0]), int(aircraft_box[1]) - 30, NAVY)
    for name, z in zones.items():
        _label(img, f"zone  {name}", int(z[0]) + 4, int(z[1]) + 4, ORANGE, 0.58)
    if active_zone in zones:
        z = zones[active_zone]
        if n_in:
            txt = f"equipment at hold: {n_in} vehicle box{'es' if n_in > 1 else ''}  max c={best_c:.2f}"
            _label(img, txt, int(z[0]) + 4, int(z[1]) + 36, GREEN, 0.58)
        else:
            _label(img, "zone clear: no equipment", int(z[0]) + 4, int(z[1]) + 36, ORANGE, 0.58)
    cv2.imwrite(str(out_png), img, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    return out_png


def write_overlays(
    run_dir: Path,
    frame_ids: list[str],
    frame_index_of: dict[str, int],
    aircraft: dict[int, list[Det]],
    vehicles: dict[int, list[Det]],
    zones_cfg: dict,
    active_zone: str | None,
    tau: float,
    nose_right: bool = False,
) -> dict[str, str]:
    """Write display/<id>_overlay.png for each frame id. Returns {frame_id: relative path}."""
    out: dict[str, str] = {}
    for fid in frame_ids:
        idx = frame_index_of.get(fid)
        if idx is None:
            continue
        ab = aircraft_box_for(idx, aircraft)
        zones = all_zones(ab, zones_cfg, nose_right) if ab else {}
        vs = vehicles.get(idx, [])
        p = draw_overlay(
            run_dir / "display" / f"{fid}.png",
            run_dir / "display" / f"{fid}_overlay.png",
            ab,
            zones,
            vs,
            active_zone,
            tau,
        )
        if p:
            out[fid] = f"display/{fid}_overlay.png"
    return out


def write_occupancy(
    run_dir: Path,
    zone_name: str,
    series: list[tuple[int, float, float]],
    cycles: dict,
    hits: list,
    *,
    fps: float,
    step: int,
    tau: float,
    n_frames: int,
    speed: float | None,
) -> Path:
    """The exact numbers the rule ran on, so the console can draw the timeline honestly."""
    doc = {
        "zone": zone_name,
        "fps": fps,
        "step": step,
        "tau": tau,
        "n_frames": n_frames,
        "speed_factor": speed,
        "series": [[f, round(ov, 3), round(c, 3)] for f, ov, c in series],
        "cycles": {
            z: [
                {
                    "start": c.start,
                    "end": c.end,
                    "conf": c.conf,
                    "present_at_clip_start": c.present_at_clip_start,
                    "departure_at_clip_end": c.departure_at_clip_end,
                }
                for c in cs
            ]
            for z, cs in cycles.items()
        },
        "hits": [
            {"name": h.name, "frame_index": h.frame_index, "confidence": h.confidence} for h in hits
        ],
    }
    p = run_dir / "occupancy.json"
    p.write_text(json.dumps(doc))
    return p
