"""Day 0 smoke test for SAM 3.1 via the Meta Model API.

Usage:
  python scripts/smoke_sam.py image path/to/frame.png "belt loader"
  python scripts/smoke_sam.py video path/to/clip.mp4 "belt loader"

Prints the RAW streamed output so we learn the token grammar from reality,
then saves it under data/smoke/ for the parser work on Day 1.
"""

from __future__ import annotations

import base64
import mimetypes
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
BASE_URL = "https://api.meta.ai/v1"
OUT_DIR = Path("data/smoke")


def client() -> OpenAI:
    key = os.environ.get("MODEL_API_KEY")
    if not key:
        sys.exit("MODEL_API_KEY missing — put it in .env")
    return OpenAI(base_url=BASE_URL, api_key=key)


def data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def upload(c: OpenAI, path: Path) -> str:
    with path.open("rb") as fh:
        f = c.files.create(file=fh, purpose="user_data")
    print(f"uploaded {path.name} -> file_id={f.id}")
    return f.id


def run(kind: str, path: Path, prompt: str) -> None:
    c = client()
    if kind == "image":
        part = {"type": "input_image", "image_url": data_url(path)}
    elif kind == "video":
        part = {"type": "input_video", "file_id": upload(c, path)}
    else:
        sys.exit("kind must be image or video")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"sam_{kind}_{path.stem}_{prompt.replace(' ', '_')}.txt"
    t0 = time.time()
    chunks: list[str] = []
    with c.responses.stream(
        model="sam-3.1",
        input=[
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}, part],
            }
        ],
        metadata={
            "include_confidence": "true",
            "mask_encoding": "one_bit",
            "propagation_direction": "forward",
        },
    ) as stream:
        for event in stream:
            if event.type == "response.output_text.delta":
                chunks.append(event.delta)
                sys.stdout.write(event.delta)
                sys.stdout.flush()
            elif event.type == "response.completed":
                print("\n[completed]")
    raw = "".join(chunks)
    out.write_text(raw)
    print(f"\n--- {len(raw)} chars in {time.time() - t0:.1f}s -> {out}")
    print("Look for: frame markers <Nf>, box tokens <|box;...|>, mask tokens, confidence c=")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    run(sys.argv[1], Path(sys.argv[2]), sys.argv[3])
