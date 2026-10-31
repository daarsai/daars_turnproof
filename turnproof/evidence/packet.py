"""Build, hash, sign and write the evidence packet (schema 0.1)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from turnproof.evidence.canonical import packet_hash
from turnproof.evidence.sign import load_private, sign_hash
from turnproof.reason.schemas import Packet

SCHEMA_VERSION = "0.1"
DATA_LABEL = "synthetic test data on licensed footage"


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def build(
    *,
    packet_id: str,
    clip_meta: dict,
    source: dict,
    time_sync: dict,
    airline_claim: dict,
    handler_log: list[dict],
    milestones: list[dict],
    observed_facts: list[dict],
    discrepancies: list[dict],
    proposed: dict,
    evidence_frames: list[dict],
    models: dict,
    chain_head: str,
    human_statement: dict | None = None,
) -> dict:
    p = {
        "packet_id": packet_id,
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": now(),
        "station": clip_meta["station"],
        "stand": clip_meta["stand"],
        "flight": {
            "number": clip_meta["flight_number"],
            "date": clip_meta["flight_date"],
            "airline": clip_meta["airline"],
            "registration": clip_meta.get("registration"),
        },
        "parties": {"handler": clip_meta["handler"], "airline": clip_meta["airline"]},
        "data_label": DATA_LABEL,
        "source": source,
        "time_sync": time_sync,
        "airline_claim": {
            "delay_code": str(airline_claim["delay_code"]),
            "minutes": int(airline_claim["minutes"]),
            "source": airline_claim.get("source", "synthetic test data"),
        },
        "handler_log": handler_log,
        "milestones": milestones,
        "observed_facts": observed_facts,
        "discrepancies": discrepancies,
        "proposed_claim": proposed,
        "evidence_frames": evidence_frames,
        "models": models,
        "human_statement": human_statement,
        "review": {
            "decision": "pending",
            "operator": None,
            "t_utc": None,
            "note": "",
            "corrections": [],
        },
        "counterparty": {"state": "PENDING", "actor": None, "t_utc": None, "reason": None},
        "chain": {"event_log_head_sha256": chain_head, "prev_packet_sha256": None},
        "packet_sha256": "",
        "signature": {"alg": "Ed25519", "key_id": "", "sig_base64": ""},
    }
    return p


def sign_and_write(p: dict, out_path: Path, key_id: str) -> dict:
    key_path = os.environ.get("TURNPROOF_SIGNING_KEY", "keys/turnproof-demo-2026.pem")
    p["packet_sha256"] = packet_hash(p)
    p["signature"] = sign_hash(load_private(key_path), p["packet_sha256"], key_id)
    Packet.model_validate(p)  # schema gate before anything leaves the system
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(p, indent=1, sort_keys=True))
    return p
