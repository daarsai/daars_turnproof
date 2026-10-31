"""Extract frames from a clip for smoke tests and zone calibration.

Usage: python scripts/extract_frames.py clips/clip1.mp4 --fps 1
Writes data/frames/<stem>/f%04d.png and prints fps, frame count, duration.
Also writes a 10 s H.264 excerpt clips/<stem>_10s.mp4 for the SAM video smoke test (needs ffmpeg).
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import cv2


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("--fps", type=float, default=1.0)
    a = ap.parse_args()
    src = Path(a.clip)
    out = Path("data/frames") / src.stem
    out.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, round(fps / a.fps))
    i = saved = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % step == 0:
            cv2.imwrite(str(out / f"f{i:04d}.png"), frame, [cv2.IMWRITE_PNG_COMPRESSION, 3])
            saved += 1
        i += 1
    cap.release()
    print(
        f"{src.name}: fps={fps:.2f} frames={n} duration={n / fps:.1f}s -> saved {saved} PNGs in {out}"
    )

    excerpt = src.with_name(f"{src.stem}_10s.mp4")
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-t",
        "10",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-an",
        str(excerpt),
    ]
    try:
        subprocess.run(cmd, check=True)
        print(f"wrote {excerpt} (10 s H.264 excerpt for SAM video smoke test)")
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        print(f"ffmpeg excerpt skipped: {e}")


if __name__ == "__main__":
    main()
