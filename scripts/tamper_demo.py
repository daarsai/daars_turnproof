"""Tamper demo for the video: copy a run's display frames, flip one pixel in one evidence
frame, and run the verifier on the copy (expected: FAIL). The original run is untouched.

Usage: python scripts/tamper_demo.py data/runs/<run_id>/packets/<packet>.json
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import cv2


def main(packet_path: Path) -> int:
    run_dir = packet_path.parent.parent
    packet = json.loads(packet_path.read_text())
    tampered = run_dir / "tampered_display"
    if tampered.exists():
        shutil.rmtree(tampered)
    shutil.copytree(run_dir / "display", tampered)
    fid = packet["evidence_frames"][-1]["id"]
    p = tampered / f"{fid}.png"
    img = cv2.imread(str(p))
    y, x = img.shape[0] // 2, img.shape[1] // 2
    img[y, x, 0] = (int(img[y, x, 0]) + 1) % 256  # one channel, one pixel
    cv2.imwrite(str(p), img, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    print(f"changed one pixel in {p}\n")
    cmd = [sys.executable, "verify_packet.py", str(packet_path), "--frames", str(tampered),
           "--log", str(run_dir / "eventlog.jsonl")]  # fmt: skip
    return subprocess.run(cmd, check=False).returncode


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    rc = main(Path(sys.argv[1]))
    print("\nexpected exit code 1 (tamper detected); got", rc)
    sys.exit(0 if rc == 1 else 2)
