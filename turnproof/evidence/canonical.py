"""Canonical JSON and hashing — shared by the pipeline and verify_packet.py.

Keep this module dependency-free (stdlib only) so the verifier can vendor it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

EXCLUDED_FROM_PACKET_HASH = ("packet_sha256", "signature")


def canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_obj(obj: Any) -> str:
    return sha256_hex(canonical_bytes(obj))


def packet_hash(packet: dict) -> str:
    body = {k: v for k, v in packet.items() if k not in EXCLUDED_FROM_PACKET_HASH}
    return hash_obj(body)


def chain_genesis(run_id: str) -> str:
    return sha256_hex(run_id.encode("utf-8"))


def chain_next(prev_hash: str, record: dict) -> str:
    # seq is assigned by the store after hashing; hash is the field being computed.
    body = {k: v for k, v in record.items() if k not in ("hash", "seq")}
    return sha256_hex(prev_hash.encode("utf-8") + canonical_bytes(body))


def rebuild_chain(run_id: str, records: list[dict]) -> str:
    """Return the head hash; raises ValueError on the first record whose stored hash mismatches."""
    h = chain_genesis(run_id)
    for i, rec in enumerate(records):
        expected = chain_next(h, rec)
        if rec.get("hash") != expected:
            raise ValueError(f"chain broken at seq {rec.get('seq', i)}")
        h = expected
    return h
