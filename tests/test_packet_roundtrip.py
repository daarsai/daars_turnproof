"""Build a packet with fake frames, sign it, run verify_packet.py, then tamper and expect FAIL."""

import json
import os
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from turnproof.events.eventlog import EventLog
from turnproof.evidence import discrepancy
from turnproof.evidence import packet as packet_mod
from turnproof.evidence.canonical import sha256_hex

ROOT = Path(__file__).parent.parent
VERIFIER = ROOT / "verify_packet.py"


def _keys(tmp: Path) -> Path:
    priv = ed25519.Ed25519PrivateKey.generate()
    pem = tmp / "k.pem"
    pem.write_bytes(
        priv.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    (tmp / "k.pub").write_bytes(
        priv.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    return pem


def _verify(packet: Path, frames: Path, log: Path, pub: Path) -> int:
    r = subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            str(packet),
            "--frames",
            str(frames),
            "--log",
            str(log),
            "--pub",
            str(pub),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    print(r.stdout)
    return r.returncode


def test_packet_sign_verify_and_tamper(tmp_path, monkeypatch):
    pem = _keys(tmp_path)
    monkeypatch.setenv("TURNPROOF_SIGNING_KEY", str(pem))
    frames = tmp_path / "display"
    frames.mkdir()
    (frames / "f00010.png").write_bytes(b"\x89PNG-fake-1")
    (frames / "f00020.png").write_bytes(b"\x89PNG-fake-2")

    log = EventLog(tmp_path / "e.db", "run-x")
    log.append("system", "ingested", {"frames": 2})
    log.append("system", "milestones_detected", {}, "OBSERVED", "CANDIDATE")
    head = log.head()
    log.append("system", "packet_built", {"packet_id": "TP-TEST-1"})  # appended AFTER the head
    log.export_jsonl(tmp_path / "eventlog.jsonl")

    milestones = [
        {
            "name": "loader_docked_start",
            "t_utc": "2026-10-30T17:58:00.000Z",
            "frame_index": 10,
            "method": "sam31_vehicle_zone_overlap",
            "zone": "forward_hold",
            "confidence": 0.9,
            "evidence_frames": ["f00010"],
        },
        {
            "name": "loading_complete",
            "t_utc": "2026-10-30T18:03:50.000Z",
            "frame_index": 20,
            "method": "sam31_vehicle_zone_overlap",
            "zone": "forward_hold",
            "confidence": 0.87,
            "evidence_frames": ["f00020"],
        },
    ]
    claim = {
        "delay_code": "32",
        "minutes": 9,
        "source": "synthetic",
        "claim_window_utc": {"start": "2026-10-30T18:05:00Z", "end": "2026-10-30T18:14:00Z"},
    }
    rows = discrepancy.build(
        milestones, [{"milestone": "loading_complete", "t_utc": "2026-10-30T18:04:00Z"}], claim
    )
    assert rows[1]["video_supported_minutes"] == 0 and rows[1]["delta_min"] == 9
    proposed = discrepancy.proposed_claim(
        claim, rows, "32", has_loading_complete=True, synced=True, spark_agrees=True
    )
    assert proposed["minutes_supported_by_video"] == 0

    ev = [
        {
            "id": fid,
            "t_utc": None,
            "frame_index": i,
            "sha256_original": "0" * 64,
            "sha256_redacted": sha256_hex((frames / f"{fid}.png").read_bytes()),
            "redaction": "none",
            "original_ref": "none",
        }
        for fid, i in (("f00010", 10), ("f00020", 20))
    ]
    p = packet_mod.build(
        packet_id="TP-TEST-1",
        clip_meta={
            "station": "BLR",
            "stand": "D14",
            "flight_number": "XY123",
            "flight_date": "2026-10-30",
            "airline": "XY",
            "handler": "H",
            "camera_id": "cam",
        },
        source={
            "type": "upload",
            "camera_id": "cam",
            "file_sha256": "a" * 64,
            "fps": 25.0,
            "duration_s": 40.0,
        },
        time_sync={
            "status": "declared",
            "reference_start_utc": "2026-10-30T17:58:00Z",
            "measured_offset_s": None,
            "speed_factor": 1.0,
            "speed_factor_source": "estimated",
            "method": "uploader_declared",
        },
        airline_claim=claim,
        handler_log=[{"milestone": "loading_complete", "t_utc": "2026-10-30T18:04:00Z"}],
        milestones=milestones,
        observed_facts=[],
        discrepancies=rows,
        proposed=proposed,
        evidence_frames=ev,
        models={"sam": {}, "spark": {}, "asr": None, "zones_config_sha256": "b" * 64},
        chain_head=head,
    )
    out = tmp_path / "packets" / "TP-TEST-1.json"
    packet_mod.sign_and_write(p, out, "k")
    pub = tmp_path / "k.pub"

    assert _verify(out, frames, tmp_path / "eventlog.jsonl", pub) == 0

    # tamper 1: one byte in a frame
    (frames / "f00020.png").write_bytes(b"\x89PNG-fake-2x")
    assert _verify(out, frames, tmp_path / "eventlog.jsonl", pub) == 1
    (frames / "f00020.png").write_bytes(b"\x89PNG-fake-2")
    assert _verify(out, frames, tmp_path / "eventlog.jsonl", pub) == 0

    # tamper 2: edit a milestone time in the JSON
    d = json.loads(out.read_text())
    d["milestones"][1]["t_utc"] = "2026-10-30T18:13:50.000Z"
    out.write_text(json.dumps(d))
    assert _verify(out, frames, tmp_path / "eventlog.jsonl", pub) == 1
    assert os.environ["TURNPROOF_SIGNING_KEY"] == str(pem)


def test_supported_minutes_cases():
    claim = {"claim_window_utc": {"start": "2026-10-30T18:05:00Z", "end": "2026-10-30T18:14:00Z"}}
    f = discrepancy.video_supported_minutes
    assert f(claim, "2026-10-30T18:03:50Z") == 0  # finished before the window
    assert f(claim, "2026-10-30T18:08:00Z") == 3  # 3 of the 9 minutes still loading
    assert f(claim, "2026-10-30T18:20:00Z") == 9  # loading ran through the whole window
    assert f(claim, None) is None  # unsynced clip
    assert f({}, "2026-10-30T18:08:00Z") is None  # no window declared
