"""Outbound webhooks: when a packet is sent (or answered), POST it to the other side's system.

Targets come from data/webhooks.json ([{url, secret, events}]), or config/webhooks_demo.json
for the demo, or TURNPROOF_WEBHOOK_URL / TURNPROOF_WEBHOOK_SECRET in the environment.
Every delivery is signed: X-TurnProof-Signature = hex(HMAC-SHA256(secret, body)). The receiver
can verify the body with the shared secret, and the packet inside it with the public key.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx

EVENTS = ("packet.sent", "packet.acknowledged", "packet.disputed")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def targets(data_dir: Path = Path("data")) -> list[dict]:
    out: list[dict] = []
    for p in (data_dir / "webhooks.json", Path("config/webhooks_demo.json")):
        if p.exists():
            out = json.loads(p.read_text())
            break
    env_url = os.environ.get("TURNPROOF_WEBHOOK_URL")
    if env_url:
        out.append(
            {
                "url": env_url,
                "secret": os.environ.get("TURNPROOF_WEBHOOK_SECRET", ""),
                "events": list(EVENTS),
            }
        )
    base = os.environ.get("TURNPROOF_BASE_URL", "http://127.0.0.1:8090")
    for t in out:
        t["url"] = t["url"].replace("{base_url}", base)
    return out


def sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify(secret: str, body: bytes, signature: str | None) -> bool:
    return bool(signature) and hmac.compare_digest(sign(secret, body), signature)


def payload(event: str, run_id: str, packet: dict, base_url: str) -> dict:
    pid = packet["packet_id"]
    return {
        "event": event,
        "sent_at_utc": _now(),
        "run_id": run_id,
        "packet_id": pid,
        "packet_sha256": packet["packet_sha256"],
        "flight": packet["flight"],
        "station": packet["station"],
        "stand": packet["stand"],
        "proposed_claim": packet["proposed_claim"],
        "links": {
            "page": f"{base_url}/packets/{pid}",
            "json": f"{base_url}/packets/{pid}.json",
            "pdf": f"{base_url}/packets/{pid}.pdf",
            "frames_zip": f"{base_url}/packets/{pid}/frames.zip",
            "verify": f"{base_url}/verify",
        },
        "packet": packet,
    }


def deliver(
    event: str, run_id: str, packet: dict, data_dir: Path = Path("data"), timeout_s: float = 8.0
) -> list[dict]:
    """POST to every target subscribed to `event`. Never raises; returns one result per target."""
    base = os.environ.get("TURNPROOF_BASE_URL", "http://127.0.0.1:8090")
    results = []
    for t in targets(data_dir):
        if event not in (t.get("events") or EVENTS):
            continue
        body = json.dumps(payload(event, run_id, packet, base), sort_keys=True).encode()
        headers = {
            "Content-Type": "application/json",
            "X-TurnProof-Event": event,
            "X-TurnProof-Signature": sign(t.get("secret", ""), body),
        }
        rec = {
            "t_utc": _now(),
            "event": event,
            "url": t["url"],
            "ok": False,
            "status": None,
            "error": None,
        }
        try:
            r = httpx.post(t["url"], content=body, headers=headers, timeout=timeout_s)
            rec["status"] = r.status_code
            rec["ok"] = r.is_success
            if not r.is_success:
                rec["error"] = r.text[:200]
        except httpx.HTTPError as e:
            rec["error"] = f"{type(e).__name__}: {e}"
        results.append(rec)
    return results
