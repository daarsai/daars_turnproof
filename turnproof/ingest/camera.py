"""Stand cameras: record a window of a live stream into a clip the pipeline can run.

Works with anything ffmpeg can open: RTSP (the normal case for a VMS or an ONVIF camera),
HTTP/HLS, or a file path (used by the tests and by the demo's looped test stream). The clip is
copied, not re-encoded, when the stream is already H.264; the pipeline re-wraps it if needed.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

VIEWS = ("front_quarter", "side", "nose")


@dataclass
class Camera:
    id: str
    stand: str
    station: str
    url: str
    view: str = "front_quarter"
    speed_factor: float = 1.0  # 1.0 for a real camera; >1 only for a time-lapse test stream
    speed_factor_source: str = "declared_by_uploader"
    note: str = ""

    def public(self) -> dict:
        """The camera without credentials in the URL (rtsp://user:pass@host -> rtsp://host)."""
        d = asdict(self)
        d["url"] = redact_url(self.url)
        return d


def redact_url(url: str) -> str:
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        return f"{scheme}://{rest.split('@', 1)[1]}"
    return url


def load_cameras(path: Path) -> list[Camera]:
    if not path.exists():
        return []
    return [Camera(**c) for c in json.loads(path.read_text())]


def save_cameras(path: Path, cameras: list[Camera]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(c) for c in cameras], indent=1))


def probe(url: str, timeout_s: int = 15) -> dict:
    """ffprobe the stream: codec, size, fps. Returns {"ok", "codec", "width", "height", "fps",
    "error"} and never raises (the console shows the result)."""
    cmd = [
        "ffprobe", "-v", "error", "-rtsp_transport", "tcp", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,r_frame_rate", "-of", "json", url,
    ]  # fmt: skip
    if not url.startswith("rtsp"):
        cmd = [c for c in cmd if c not in ("-rtsp_transport", "tcp")]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, check=False)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    if r.returncode != 0:
        return {"ok": False, "error": (r.stderr or "ffprobe failed").strip()[:300]}
    try:
        st = json.loads(r.stdout)["streams"][0]
        num, den = st.get("r_frame_rate", "0/1").split("/")
        fps = round(float(num) / float(den), 3) if float(den) else None
        return {
            "ok": True,
            "codec": st.get("codec_name"),
            "width": st.get("width"),
            "height": st.get("height"),
            "fps": fps,
            "error": None,
        }
    except (ValueError, KeyError, IndexError) as e:
        return {"ok": False, "error": f"unexpected ffprobe output: {e}"}


def _ffmpeg_cmd(url: str, seconds: float, out_path: Path, codec: list[str]) -> list[str]:
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if url.startswith("rtsp"):
        cmd += ["-rtsp_transport", "tcp"]
    cmd += ["-i", url, "-t", str(seconds), "-an", *codec, "-movflags", "+faststart", str(out_path)]
    return cmd


def record(url: str, seconds: float, out_path: Path) -> Path:
    """Record `seconds` of the stream into out_path (mp4). Raises RuntimeError on failure.
    Copies the H.264 stream as-is; re-encodes once if the stream cannot be copied."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    attempts = (["-c:v", "copy"], ["-c:v", "libx264", "-preset", "veryfast"])
    err = ""
    for codec in attempts:
        try:
            r = subprocess.run(
                _ffmpeg_cmd(url, seconds, out_path, codec),
                capture_output=True,
                text=True,
                timeout=seconds + 120,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"recording timed out after {seconds + 120:.0f} s") from e
        if r.returncode == 0 and out_path.exists() and out_path.stat().st_size >= 1024:
            return out_path
        err = (r.stderr or "ffmpeg failed").strip()[:400]
    raise RuntimeError(err)


def snapshot(url: str, out_path: Path, timeout_s: int = 20) -> Path | None:
    """One JPEG frame from the stream, so the operator can see what the camera sees."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if url.startswith("rtsp"):
        cmd += ["-rtsp_transport", "tcp"]
    cmd += ["-i", url, "-frames:v", "1", "-q:v", "4", str(out_path)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, check=False)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    return out_path if r.returncode == 0 and out_path.exists() else None
