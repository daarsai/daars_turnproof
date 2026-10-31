"""Clip probing, re-encoding, frame extraction with hashing and encryption."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2

from turnproof.evidence.canonical import sha256_hex
from turnproof.ingest.crypto import hash_and_encrypt


@dataclass
class ClipInfo:
    path: Path
    fps: float
    frames: int
    width: int
    height: int
    duration_s: float
    sha256: str


def probe(path: Path) -> ClipInfo:
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return ClipInfo(path, fps, n, w, h, n / fps if fps else 0.0, sha256_hex(path.read_bytes()))


def ensure_h264(src: Path, dst: Path) -> Path:
    """SAM accepts MP4/MOV with H.264/H.265. Re-encode once to a faststart MP4 (idempotent)."""
    if dst.exists():
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(dst),
    ]  # fmt: skip
    subprocess.run(cmd, check=True)
    return dst


def ref_time(reference_start_utc: str | None, idx: int, fps: float) -> str | None:
    if not reference_start_utc:
        return None
    t0 = datetime.fromisoformat(reference_start_utc).astimezone(UTC)
    t = t0 + timedelta(seconds=idx / fps)
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def extract(
    clip: Path,
    out_dir: Path,
    data_key: bytes | None,
    reference_start_utc: str | None,
    every: int = 1,
) -> dict[int, dict]:
    """Extract every `every`-th frame. Hash original PNG bytes, encrypt originals, keep a display
    copy (redaction is applied later by redact.py). Returns {idx: frame_record}."""
    disp = out_dir / "display"
    enc = out_dir / "enc"
    disp.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(clip))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    records: dict[int, dict] = {}
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % every == 0:
            _ok, buf = cv2.imencode(".png", frame, [cv2.IMWRITE_PNG_COMPRESSION, 3])
            png = buf.tobytes()
            fid = f"f{idx:05d}"
            if data_key:
                h_orig = hash_and_encrypt(png, fid, enc / f"{fid}.bin", data_key)
            else:
                h_orig = sha256_hex(png)
            (disp / f"{fid}.png").write_bytes(png)
            records[idx] = {
                "id": fid,
                "frame_index": idx,
                "t_raw_s": round(idx / fps, 3),
                "t_utc": ref_time(reference_start_utc, idx, fps),
                "sha256_original": h_orig,
                "sha256_redacted": None,
                "redaction": "none",
                "original_ref": f"enc/{fid}.bin" if data_key else None,
            }
        idx += 1
    cap.release()
    (out_dir / "frames.json").write_text(json.dumps(records, indent=1))
    return records
