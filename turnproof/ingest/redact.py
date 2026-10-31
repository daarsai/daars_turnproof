"""Blur persons in display frames using SAM 'person' boxes (box blur fallback; masks optional)."""

from __future__ import annotations

import json
from pathlib import Path

import cv2

from turnproof.evidence.canonical import sha256_hex
from turnproof.perception.sam_parse import Det


def blur_boxes(img, boxes: list[tuple[float, float, float, float]]):
    for x1, y1, x2, y2 in boxes:
        x1, y1 = max(0, int(x1)), max(0, int(y1))
        x2, y2 = min(img.shape[1], int(x2) + 1), min(img.shape[0], int(y2) + 1)
        if x2 - x1 < 2 or y2 - y1 < 2:
            continue
        k = max(7, ((y2 - y1) // 4) | 1)
        img[y1:y2, x1:x2] = cv2.GaussianBlur(img[y1:y2, x1:x2], (k, k), 0)
    return img


def redact_display_frames(out_dir: Path, persons: dict[int, list[Det]], records: dict[int, dict]):
    """Blur persons in place on display/*.png, record sha256_redacted. Frames with no person
    detections are still hashed so every display frame has a redacted hash."""
    disp = out_dir / "display"
    for idx, rec in records.items():
        p = disp / f"{rec['id']}.png"
        img = cv2.imread(str(p))
        boxes = [d.box for d in persons.get(idx, [])]
        if boxes:
            img = blur_boxes(img, boxes)
            rec["redaction"] = "persons_blurred_sam31_box"
        else:
            rec["redaction"] = "no_person_detected"
        _ok, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 3])
        png = buf.tobytes()
        p.write_bytes(png)
        rec["sha256_redacted"] = sha256_hex(png)
    (out_dir / "frames.json").write_text(json.dumps(records, indent=1))
    return records
