"""Muse Spark 1.3 client: keyframes + structured context -> validated SparkOut. Cached on disk."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path

from openai import OpenAI
from pydantic import ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential

from turnproof.evidence.canonical import sha256_hex
from turnproof.reason.prompts import PROMPT_VERSION, SYSTEM, user_text
from turnproof.reason.schemas import SparkOut

BASE_URL = "https://api.meta.ai/v1"
MODEL = "muse-spark-1.3"


class SparkClient:
    def __init__(self, cache_dir: Path, model: str = MODEL, effort: str = "medium"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.model, self.effort = model, effort
        self._key = os.environ.get("MODEL_API_KEY")
        self._client: OpenAI | None = None
        self.calls: list[dict] = []
        self.prompt_sha256 = sha256_hex(SYSTEM.encode())
        self.prompt_version = PROMPT_VERSION

    def evaluate(self, frames: list[Path], frame_ids: list[str], context: dict) -> dict:
        """Returns {"ok": bool, "out": SparkOut|None, "raw": str, "path": "A|B|failed", ...}."""
        key = self._cache_key(frames, context)
        hit = self.cache_dir / f"{key}.json"
        if hit.exists():
            cached = json.loads(hit.read_text())
            self.calls.append({"cached": True, "seconds": 0, "tokens_in": 0, "tokens_out": 0})
            return cached
        result = self._call(frames, frame_ids, context)
        hit.write_text(json.dumps(result, indent=1))
        return result

    # -- internals -----------------------------------------------------------
    def _cli(self) -> OpenAI:
        if self._client is None:
            if not self._key:
                raise RuntimeError("MODEL_API_KEY missing and no Spark cache hit")
            self._client = OpenAI(base_url=BASE_URL, api_key=self._key)
        return self._client

    def _cache_key(self, frames: list[Path], context: dict) -> str:
        h = hashlib.sha256(SYSTEM.encode())
        for f in frames:
            h.update(f.read_bytes())
        h.update(json.dumps(context, sort_keys=True).encode())
        h.update(self.model.encode())
        return h.hexdigest()[:20]

    def _messages(self, frames: list[Path], frame_ids: list[str], context: dict, extra: str):
        content = [
            {
                "type": "text",
                "text": user_text(context, frame_ids, SparkOut.model_json_schema()) + extra,
            }
        ]
        for f in frames:
            b64 = base64.b64encode(f.read_bytes()).decode()
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
            )
        return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=8), reraise=True)
    def _chat(self, messages: list[dict], response_format: dict | None):
        kw = {
            "model": self.model,
            "messages": messages,
            "extra_body": {"reasoning_effort": self.effort},
        }
        if response_format:
            kw["response_format"] = response_format
        return self._cli().chat.completions.create(**kw)

    def _call(self, frames: list[Path], frame_ids: list[str], context: dict) -> dict:
        t0 = time.time()
        schema_fmt = {
            "type": "json_schema",
            "json_schema": {
                "name": "spark_out",
                "strict": True,
                "schema": SparkOut.model_json_schema(),
            },
        }
        # Path A: structured outputs
        try:
            r = self._chat(self._messages(frames, frame_ids, context, ""), schema_fmt)
            raw = r.choices[0].message.content or ""
            out = SparkOut.model_validate_json(_strip_fences(raw))
            return self._done(out, raw, "A", r, t0)
        except Exception as e:  # noqa: BLE001 - fall through to path B with the reason recorded
            err_a = f"{type(e).__name__}: {str(e)[:200]}"
        # Path B: instruction + validate + one retry
        extra = ""
        last_raw = ""
        for _attempt in (1, 2):
            r = self._chat(self._messages(frames, frame_ids, context, extra), None)
            last_raw = r.choices[0].message.content or ""
            try:
                out = SparkOut.model_validate_json(_strip_fences(last_raw))
                return self._done(out, last_raw, "B", r, t0, err_a)
            except ValidationError as ve:
                extra = (
                    "\nPrevious output was invalid: " + str(ve.errors()[:3]) + "\nReturn JSON only."
                )
        self.calls.append({"cached": False, "seconds": round(time.time() - t0, 2), "failed": True})
        return {"ok": False, "out": None, "raw": last_raw, "path": "failed", "error_a": err_a}

    def _done(
        self, out: SparkOut, raw: str, path: str, r, t0: float, err_a: str | None = None
    ) -> dict:
        u = getattr(r, "usage", None)
        self.calls.append(
            {
                "cached": False,
                "seconds": round(time.time() - t0, 2),
                "tokens_in": getattr(u, "prompt_tokens", 0) or 0,
                "tokens_out": getattr(u, "completion_tokens", 0) or 0,
                "path": path,
            }
        )
        return {"ok": True, "out": out.model_dump(), "raw": raw, "path": path, "error_a": err_a}


def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        s = s.removesuffix("```").strip()
    return s
