"""Aircraft-relative zones: hold regions derived from the aircraft bounding box.

A box is (x1, y1, x2, y2) in pixels, inclusive-exclusive like numpy slicing is NOT assumed;
we treat them as plain float rectangles. Fractions come from config.zones.
x runs along the fuselage from nose (0) to tail (1); y runs top (0) to bottom (1).
Fractions are written for a nose-LEFT view; pass nose_right=True to mirror them.
"""

from __future__ import annotations

Box = tuple[float, float, float, float]


def zone_from_aircraft(aircraft: Box, frac: dict, nose_right: bool = False) -> Box:
    ax1, ay1, ax2, ay2 = aircraft
    w, h = ax2 - ax1, ay2 - ay1
    x0, x1 = frac["x0"], frac["x1"]
    if nose_right:
        x0, x1 = 1 - x1, 1 - x0
    pad = frac.get("pad_out", 0.0) * h
    return (ax1 + x0 * w, ay1 + frac["y0"] * h, ax1 + x1 * w, ay1 + frac["y1"] * h + pad)


def area(b: Box) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def intersection(a: Box, b: Box) -> Box:
    return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))


def overlap_ratio(obj: Box, zone: Box) -> float:
    """Share of the object's box that lies inside the zone (0..1)."""
    a = area(obj)
    return area(intersection(obj, zone)) / a if a > 0 else 0.0


def all_zones(aircraft: Box, zones_cfg: dict, nose_right: bool = False) -> dict[str, Box]:
    return {
        name: zone_from_aircraft(aircraft, frac, nose_right) for name, frac in zones_cfg.items()
    }
