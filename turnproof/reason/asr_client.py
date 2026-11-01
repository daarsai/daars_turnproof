"""Muse Voice Transcribe: a short spoken operator statement -> text.

POST /v1/asr/transcribe, multipart with exactly two parts: `request` (JSON: model,
audioEncoding) and `audio` (the WAV bytes). Shape confirmed on 31 Oct 2026 by the smoke test.
Browser recordings (webm/ogg) are converted to 16 kHz mono WAV with ffmpeg first.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import httpx

MODEL = "muse-voice-transcribe-1.0"
URL = "https://api.meta.ai/v1/asr/transcribe"


def to_wav(audio_bytes: bytes, suffix: str = ".webm") -> bytes:
    """Any ffmpeg-readable audio -> 16 kHz mono PCM WAV."""
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"in{suffix}"
        dst = Path(td) / "out.wav"
        src.write_bytes(audio_bytes)
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src)]
        cmd += ["-ac", "1", "-ar", "16000", "-f", "wav", str(dst)]
        subprocess.run(cmd, check=True, capture_output=True)
        return dst.read_bytes()


def _extract_text(body: dict | list | str) -> str:
    """Be tolerant about the response shape: look for the usual transcript keys."""
    if isinstance(body, str):
        return body.strip()
    if isinstance(body, list):
        return " ".join(_extract_text(b) for b in body).strip()
    for k in ("text", "transcript", "transcription"):
        v = body.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    for k in ("result", "results", "output", "segments", "data"):
        v = body.get(k)
        if v:
            t = _extract_text(v)
            if t:
                return t
    return ""


def transcribe(wav_bytes: bytes, api_key: str | None = None, model: str = MODEL) -> dict:
    """Returns {"text": ..., "model": ..., "raw": <response json>}. Raises on HTTP errors."""
    key = api_key or os.environ.get("MODEL_API_KEY")
    if not key:
        raise RuntimeError("MODEL_API_KEY missing")
    with httpx.Client(timeout=120) as c:
        r = c.post(
            URL,
            headers={"Authorization": f"Bearer {key}"},
            files={
                "request": (
                    None,
                    json.dumps({"model": model, "audioEncoding": "WAV"}),
                    "application/json",
                ),
                "audio": ("statement.wav", wav_bytes, "audio/wav"),
            },
        )
        r.raise_for_status()
        try:
            body = r.json()
        except ValueError:
            body = r.text
        return {"text": _extract_text(body), "model": model, "raw": body}
