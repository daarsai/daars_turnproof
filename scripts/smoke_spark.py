"""Day 0 smoke test for Muse Spark 1.3: image input + strict JSON output.

Usage:
  python scripts/smoke_spark.py path/to/frame.png [more frames...]

Tries structured output via response_format=json_schema first; on any error
falls back to a 'JSON only' instruction + pydantic validation + one retry.
Report which path worked — that decides reason/spark_client.py on Day 2.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError

load_dotenv()
BASE_URL = "https://api.meta.ai/v1"
MODEL = "muse-spark-1.3"


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    frames: list[str]


class RuleCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim: str
    agree: bool
    reason: str


class SparkOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observed_facts: list[Fact]
    hold_door_state: str = Field(pattern="^(open|closed|unknown)$")
    rule_claim_check: RuleCheck
    candidate_delay_code_family: str = Field(pattern="^(3[1-9]|none)$")
    confidence: float = Field(ge=0, le=1)
    requires_operator_review: bool


SYSTEM = (
    "You evaluate aircraft turnaround keyframes for an evidence tool. "
    "Report only what is visible. Cite frame ids. Separate observations from hypotheses. "
    "Never assign responsibility or a final delay code. Return JSON only, matching the schema."
)

USER_CTX = {
    "rule_claim": "loader_docked",
    "milestone_times_utc": {"loader_docked_start": "2026-10-30T17:58:04Z"},
    "zones": ["aft_hold"],
    "airline_claim": {"delay_code": "32", "minutes": 9, "source": "synthetic test data"},
    "allowed_code_families": ["31", "32", "33", "34", "35", "36", "37", "38", "39", "none"],
}


def img_part(p: Path) -> dict:
    b64 = base64.b64encode(p.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}


def messages(frames: list[Path], extra: str = "") -> list[dict]:
    content = [
        {
            "type": "text",
            "text": "Context:\n"
            + json.dumps(USER_CTX, indent=1)
            + "\nFrame ids in order: "
            + ", ".join(f"f{i}" for i in range(len(frames)))
            + "\nSchema:\n"
            + json.dumps(SparkOut.model_json_schema())
            + extra,
        }
    ]
    content += [img_part(p) for p in frames]
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}]


def main(frames: list[Path]) -> None:
    key = os.environ.get("MODEL_API_KEY") or sys.exit("MODEL_API_KEY missing")
    c = OpenAI(base_url=BASE_URL, api_key=key)

    # Path A: structured outputs
    t0 = time.time()
    try:
        r = c.chat.completions.create(
            model=MODEL,
            messages=messages(frames),
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "spark_out",
                    "strict": True,
                    "schema": SparkOut.model_json_schema(),
                },
            },
            extra_body={"reasoning_effort": "medium"},
        )
        txt = r.choices[0].message.content
        obj = SparkOut.model_validate_json(txt)
        print(f"PATH A (json_schema) OK in {time.time() - t0:.1f}s; usage={r.usage}")
        print(obj.model_dump_json(indent=1))
        return
    except Exception as e:  # noqa: BLE001
        print(f"PATH A failed: {type(e).__name__}: {str(e)[:300]}")

    # Path B: instruction + validate + one retry
    extra = ""
    for attempt in (1, 2):
        t0 = time.time()
        r = c.chat.completions.create(
            model=MODEL,
            messages=messages(frames, extra),
            extra_body={"reasoning_effort": "medium"},
        )
        txt = r.choices[0].message.content.strip()
        txt = txt.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            obj = SparkOut.model_validate_json(txt)
            print(f"PATH B OK on attempt {attempt} in {time.time() - t0:.1f}s; usage={r.usage}")
            print(obj.model_dump_json(indent=1))
            return
        except ValidationError as ve:
            print(f"attempt {attempt} invalid: {ve.errors()[:3]}")
            extra = "\nPrevious output was invalid: " + str(ve.errors()[:3]) + "\nReturn JSON only."
    sys.exit("Spark structured output failed both paths — report this.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main([Path(p) for p in sys.argv[1:]])
