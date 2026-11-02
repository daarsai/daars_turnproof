"""Claim intake: an airline's delay message (MVT / DLA telex line, an email, or a photo of a
delay report) -> a structured claim, extracted by Muse Spark 1.3 and CONFIRMED by a human
before it becomes an input to a run.

Spark's job here is extraction only. It never decides whether the claim is right; that is what
the video and the rule are for.
"""

from __future__ import annotations

import base64
import os
import time
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from turnproof.evidence.canonical import sha256_hex
from turnproof.reason.spark_client import BASE_URL, MODEL, _strip_fences

INTAKE_PROMPT_VERSION = "claim-intake-0.1"

SYSTEM = (
    "You extract airline delay claims for TurnProof, an evidence tool for aircraft turnaround "
    "disputes. The input is an airline message: an IATA MVT or DLA telex (for example "
    "'DLA/32/0009' or 'DL32/0009'), an email, or a photo of a delay report.\n"
    "Rules:\n"
    "1. Extract only what the message states. Never infer a delay code, minutes or times that "
    "are not in the text or image.\n"
    "2. IATA delay codes are two digits (00-99). Sub-codes may follow as a letter; report the "
    "two-digit code only. Minutes in MVT/DLA are usually HHMM after the code ('/0009' = 9 "
    "minutes, '/0112' = 1 hour 12 minutes).\n"
    "3. Times are UTC unless the message says otherwise; write ISO 8601 with a Z suffix, and "
    "null when the message gives no date or time. If only a time of day is given and a date "
    "is present elsewhere in the message, combine them; otherwise leave the field null.\n"
    "4. source_quote must be the exact characters you based the code and minutes on.\n"
    "5. confidence is your confidence that code and minutes are extracted correctly.\n"
    "6. Return JSON only, matching the schema exactly."
)


class ExtractedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    delay_code: str = Field(pattern=r"^\d{2}$")
    minutes: int = Field(ge=0, le=1440)
    flight_number: str | None
    flight_date: str | None
    airline: str | None
    station: str | None
    claim_window_start_utc: str | None
    claim_window_end_utc: str | None
    message_type: Literal["MVT", "DLA", "email", "report_image", "other"]
    source_quote: str
    confidence: float = Field(ge=0, le=1)
    notes: str


def extract_claim(
    text: str,
    image_bytes: bytes | None = None,
    image_mime: str = "image/jpeg",
    *,
    api_key: str | None = None,
    model: str = MODEL,
    effort: str = "medium",
) -> dict:
    """Returns {"ok", "claim" (ExtractedClaim dict), "raw", "tokens_in", "tokens_out",
    "seconds", "input_sha256", "prompt_version", "model", "error"}."""
    key = api_key or os.environ.get("MODEL_API_KEY")
    if not key:
        raise RuntimeError("MODEL_API_KEY missing")
    content: list[dict] = [
        {
            "type": "text",
            "text": "Airline message:\n"
            + (text.strip() or "(no text; see attached image)")
            + "\nReturn JSON matching this schema:\n"
            + str(ExtractedClaim.model_json_schema()),
        }
    ]
    if image_bytes:
        b64 = base64.b64encode(image_bytes).decode()
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{b64}"}}
        )
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}]
    fmt = {
        "type": "json_schema",
        "json_schema": {
            "name": "extracted_claim",
            "strict": True,
            "schema": ExtractedClaim.model_json_schema(),
        },
    }
    client = OpenAI(base_url=BASE_URL, api_key=key)
    t0 = time.time()
    raw = ""
    try:
        r = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format=fmt,
            extra_body={"reasoning_effort": effort},
        )
        raw = r.choices[0].message.content or ""
        claim = ExtractedClaim.model_validate_json(_strip_fences(raw))
        u = getattr(r, "usage", None)
        return {
            "ok": True,
            "claim": claim.model_dump(),
            "raw": raw,
            "tokens_in": getattr(u, "prompt_tokens", 0) or 0,
            "tokens_out": getattr(u, "completion_tokens", 0) or 0,
            "seconds": round(time.time() - t0, 2),
            "input_sha256": sha256_hex(text.encode() + (image_bytes or b"")),
            "prompt_version": INTAKE_PROMPT_VERSION,
            "model": model,
            "error": None,
        }
    except Exception as e:  # noqa: BLE001 - the operator sees the reason and can type the claim
        return {
            "ok": False,
            "claim": None,
            "raw": raw,
            "tokens_in": 0,
            "tokens_out": 0,
            "seconds": round(time.time() - t0, 2),
            "input_sha256": sha256_hex(text.encode() + (image_bytes or b"")),
            "prompt_version": INTAKE_PROMPT_VERSION,
            "model": model,
            "error": f"{type(e).__name__}: {str(e)[:300]}",
        }


def parse_mvt_locally(text: str) -> dict | None:
    """Deterministic fallback for the common telex shapes, used when Spark is unavailable and
    shown next to Spark's answer as a cross-check: DLA/32/0009, DL32/0009, DL32/0009/41/0005."""
    import re

    up = text.upper()
    m = re.search(r"\bDLA?/?(\d{2})[A-Z]?/(\d{2})(\d{2})\b", up)
    if not m:
        return None
    code, hh, mm = m.group(1), int(m.group(2)), int(m.group(3))
    out = {"delay_code": code, "minutes": hh * 60 + mm, "source_quote": m.group(0)}
    # flight number ('XY123/30' or 'XY 123'), and STD / ATD times when the message states them
    f = re.search(r"\b([A-Z]{2}\s?\d{3,4}[A-Z]?)/\d{2}", up) or re.search(
        r"\b([A-Z]{2}\s?\d{3,4})\b", up
    )
    if f:
        out["flight_number"] = f.group(1).replace(" ", "")
    for key in ("STD", "ATD"):
        t = re.search(rf"\b{key}\s*(\d{{2}}):?(\d{{2}})Z?\b", up)
        if t:
            out[key.lower()] = f"{t.group(1)}:{t.group(2)}"
    return out
