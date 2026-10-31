"""Parse SAM 3.1 special-token text into per-frame boxes.

Observed grammar (Meta Model API, 31 Oct 2026, from real responses):
    <0f>0<|box;x1=560;y1=184;x2=629;y2=269;w=1280;h=516;c=0.898|><|mask;...|>,1<|box;...|><|mask;...|>
    <1f>0<|box;...|><|mask;...|>
One line per frame, frame marker <Nf>, then comma-separated objects: ordinal, box token, mask token.
Boxes are inclusive pixel coords in the source frame of size (w, h). Masks are ignored here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

FRAME_RE = re.compile(r"<(\d+)f>")
BOX_RE = re.compile(
    r"(\d+)<\|box;x1=(-?\d+(?:\.\d+)?);y1=(-?\d+(?:\.\d+)?);x2=(-?\d+(?:\.\d+)?);"
    r"y2=(-?\d+(?:\.\d+)?);w=(\d+);h=(\d+)(?:;c=([0-9.eE+-]+))?\|>"
)


@dataclass(frozen=True)
class Det:
    frame: int
    ordinal: int
    x1: float
    y1: float
    x2: float
    y2: float
    w: int
    h: int
    c: float | None

    @property
    def box(self) -> tuple[float, float, float, float]:
        return (self.x1, self.y1, self.x2, self.y2)

    @property
    def area(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)


def parse(text: str) -> dict[int, list[Det]]:
    """Return {frame_index: [Det, ...]} keyed by frame marker (results may arrive out of order)."""
    out: dict[int, list[Det]] = {}
    # Split into frame chunks at each marker.
    parts = FRAME_RE.split(text)
    # parts = [prefix, f0, chunk0, f1, chunk1, ...]
    for i in range(1, len(parts) - 1, 2):
        frame = int(parts[i])
        chunk = parts[i + 1]
        dets = out.setdefault(frame, [])
        for m in BOX_RE.finditer(chunk):
            ordinal, x1, y1, x2, y2, w, h, c = m.groups()
            dets.append(
                Det(
                    frame,
                    int(ordinal),
                    float(x1),
                    float(y1),
                    float(x2),
                    float(y2),
                    int(w),
                    int(h),
                    float(c) if c else None,
                )
            )
    return out


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ix1, iy1, ix2, iy2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def largest(dets: list[Det]) -> Det | None:
    return max(dets, key=lambda d: d.area) if dets else None
