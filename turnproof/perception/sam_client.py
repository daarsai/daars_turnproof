"""SAM 3.1 client over the Meta Model API (Responses API, streamed), with on-disk caching.

Every raw response is cached under <cache_dir>/<sha>.txt so the pipeline, the console and the
demo video can replay without the network. Cache key = concept + file sha256 + metadata.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

BASE_URL = "https://api.meta.ai/v1"
MODEL = "sam-3.1"


class SamClient:
    def __init__(self, cache_dir: Path, api_key: str | None = None, model: str = MODEL):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.model = model
        self._key = api_key or os.environ.get("MODEL_API_KEY")
        self._client: OpenAI | None = None
        self.calls: list[dict] = []  # metrics: {concept, kind, cached, seconds, bytes}

    # -- public --------------------------------------------------------------
    def segment_video(self, video: Path, concept: str, direction: str = "forward") -> str:
        meta = {
            "include_confidence": "true",
            "mask_encoding": "one_bit",
            "propagation_direction": direction,
        }
        key = self._cache_key(video, concept, meta)
        hit = self.cache_dir / f"{key}.txt"
        if hit.exists():
            self.calls.append({"concept": concept, "kind": "video", "cached": True, "seconds": 0})
            return hit.read_text()
        file_id = self._upload(video)
        part = {"type": "input_video", "file_id": file_id}
        text = self._stream(concept, part, meta)
        hit.write_text(text)
        return text

    def segment_image(self, image: Path, concept: str) -> str:
        meta = {"include_confidence": "true", "mask_encoding": "one_bit"}
        key = self._cache_key(image, concept, meta)
        hit = self.cache_dir / f"{key}.txt"
        if hit.exists():
            self.calls.append({"concept": concept, "kind": "image", "cached": True, "seconds": 0})
            return hit.read_text()
        b64 = base64.b64encode(image.read_bytes()).decode()
        part = {"type": "input_image", "image_url": f"data:image/png;base64,{b64}"}
        text = self._stream(concept, part, meta)
        hit.write_text(text)
        return text

    # -- internals -----------------------------------------------------------
    def _cli(self) -> OpenAI:
        if self._client is None:
            if not self._key:
                raise RuntimeError("MODEL_API_KEY missing and no cache hit")
            self._client = OpenAI(base_url=BASE_URL, api_key=self._key)
        return self._client

    @staticmethod
    def _cache_key(path: Path, concept: str, meta: dict) -> str:
        h = hashlib.sha256()
        h.update(path.read_bytes())
        h.update(concept.encode())
        h.update(json.dumps(meta, sort_keys=True).encode())
        return f"{concept.replace(' ', '_')}_{h.hexdigest()[:16]}"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=8), reraise=True)
    def _upload(self, path: Path) -> str:
        with path.open("rb") as fh:
            return self._cli().files.create(file=fh, purpose="user_data").id

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=8), reraise=True)
    def _stream(self, concept: str, part: dict, meta: dict) -> str:
        t0 = time.time()
        chunks: list[str] = []
        with self._cli().responses.stream(
            model=self.model,
            input=[
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": concept}, part],
                }
            ],
            metadata=meta,
        ) as stream:
            for event in stream:
                if event.type == "response.output_text.delta":
                    chunks.append(event.delta)
        text = "".join(chunks)
        self.calls.append(
            {
                "concept": concept,
                "kind": part["type"],
                "cached": False,
                "seconds": round(time.time() - t0, 2),
                "bytes": len(text),
            }
        )
        return text
