"""Day 0 go/no-go for Muse Voice Transcribe (file endpoint).

Usage: python scripts/smoke_asr.py path/to/note.wav   (16 kHz mono WAV, <= 60 s)

Documented: POST /v1/asr/transcribe. Request body shape is undocumented in the
pages we read, so we try multipart first, then JSON+base64. If both fail in
under two hours of total effort the voice feature is DROPPED (no non-Meta STT).
"""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()
URL = "https://api.meta.ai/v1/asr/transcribe"


def main(path: Path) -> None:
    key = os.environ.get("MODEL_API_KEY") or sys.exit("MODEL_API_KEY missing")
    h = {"Authorization": f"Bearer {key}"}
    with httpx.Client(timeout=120) as c:
        r = c.post(
            URL,
            headers=h,
            data={"model": "muse-voice-transcribe-1.0"},
            files={"file": (path.name, path.read_bytes(), "audio/wav")},
        )
        print("multipart:", r.status_code, r.text[:800])
        if r.is_success:
            return
        r = c.post(
            URL,
            headers={**h, "Content-Type": "application/json"},
            json={
                "model": "muse-voice-transcribe-1.0",
                "audio": base64.b64encode(path.read_bytes()).decode(),
                "format": "wav",
            },
        )
        print("json+b64:", r.status_code, r.text[:800])
        if not r.is_success:
            print("NO-GO: drop the voice feature unless the docs show the body shape.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
