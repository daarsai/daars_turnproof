#!/usr/bin/env python3
"""Standalone verifier for a TurnProof evidence packet. Needs only Python 3.11+ and the
`cryptography` package (pip install cryptography). No TurnProof code is imported, so the
counterparty can run it on its own machine.

Usage:
  python verify_packet.py PACKET.json [--frames DIR] [--log eventlog.jsonl] [--pub KEY.pub]

Checks: schema basics, redacted frame hashes, event-log chain head, packet hash, signature.
Exit code 0 only if every check passes.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  - ' + detail) if detail else ''}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("packet")
    ap.add_argument("--frames", help="directory with redacted display frames (<id>.png)")
    ap.add_argument("--log", help="eventlog.jsonl exported with the packet")
    ap.add_argument("--pub", help="public key PEM (default: keys/<key_id>.pub)")
    a = ap.parse_args()

    p = json.loads(Path(a.packet).read_text())
    results = []

    results.append(check("schema_version is 0.1", p.get("schema_version") == "0.1"))
    required = ("packet_id", "milestones", "evidence_frames", "chain", "packet_sha256", "signature")
    results.append(check("required fields present", all(k in p for k in required)))
    results.append(
        check(
            "no possible_causes field (no machine speculation in packet)",
            "possible_causes" not in p,
        )
    )

    # frame hashes
    if a.frames:
        bad = []
        for f in p.get("evidence_frames", []):
            fp = Path(a.frames) / f"{f['id']}.png"
            if not fp.exists() or sha256_hex(fp.read_bytes()) != f.get("sha256_redacted"):
                bad.append(f["id"])
        results.append(
            check(
                f"{len(p.get('evidence_frames', []))} redacted frame hashes",
                not bad,
                ", ".join(bad),
            )
        )
    else:
        print("SKIP  frame hashes (no --frames)")

    # chain: every link must verify, and the packet's recorded head must be one of the
    # chain's hashes (the packet is built BEFORE the 'packet_built' record is appended).
    if a.log:
        recs = [json.loads(line) for line in Path(a.log).read_text().splitlines() if line.strip()]
        run_id = recs[0]["run_id"] if recs else ""
        h = sha256_hex(run_id.encode())
        seen = {h}
        ok = True
        for r in recs:
            body = {k: v for k, v in r.items() if k not in ("hash", "seq")}
            h = sha256_hex(h.encode() + canonical(body))
            if r.get("hash") != h:
                ok = False
                break
            seen.add(h)
        head = p["chain"]["event_log_head_sha256"]
        results.append(
            check(
                f"event-log chain ({len(recs)} records, packet anchored at a chain hash)",
                ok and head in seen,
                "" if ok else "a record was altered",
            )
        )
    else:
        print("SKIP  event-log chain (no --log)")

    # packet hash
    body = {k: v for k, v in p.items() if k not in ("packet_sha256", "signature")}
    results.append(check("packet hash", sha256_hex(canonical(body)) == p["packet_sha256"]))

    # signature
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization

        pub_path = a.pub or f"keys/{p['signature']['key_id']}.pub"
        pub = serialization.load_pem_public_key(Path(pub_path).read_bytes())
        try:
            pub.verify(
                base64.b64decode(p["signature"]["sig_base64"]), bytes.fromhex(p["packet_sha256"])
            )
            results.append(check(f"Ed25519 signature ({p['signature']['key_id']})", True))
        except InvalidSignature:
            results.append(check("Ed25519 signature", False, "signature does not match"))
    except ImportError:
        results.append(check("Ed25519 signature", False, "pip install cryptography"))
    except FileNotFoundError as e:
        results.append(check("Ed25519 signature", False, f"public key not found: {e.filename}"))

    ok = all(results)
    print("RESULT:", "VERIFIED" if ok else "TAMPERED OR INVALID")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
