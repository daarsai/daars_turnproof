"""Console smoke test on a synthetic run folder: pages render, decisions move the state machine
and land in the hash-chained event log, packet JSON/PDF download, verifier runs from the UI."""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi.testclient import TestClient

from turnproof.events.eventlog import EventLog
from turnproof.events.milestones import Cycle, MilestoneHit
from turnproof.evidence import packet as packet_mod
from turnproof.evidence.canonical import sha256_hex
from turnproof.perception.sam_parse import Det
from turnproof.review import app as app_mod
from turnproof.review.overlay import draw_overlay, write_occupancy
from turnproof.review.store import RunStore

RUN = "clipx-abcdef12"
PID = "TP-20261101-abcdef12"


def _keys(tmp: Path) -> tuple[Path, Path]:
    priv = ed25519.Ed25519PrivateKey.generate()
    pem, pub = tmp / "k.pem", tmp / "k.pub"
    pem.write_bytes(
        priv.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    pub.write_bytes(
        priv.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    return pem, pub


def _png(path: Path, seed: int) -> bytes:
    img = np.full((120, 300, 3), 40 + seed, np.uint8)
    cv2.imwrite(str(path), img)
    return path.read_bytes()


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    pem, pub = _keys(tmp_path)
    monkeypatch.setenv("TURNPROOF_SIGNING_KEY", str(pem))
    monkeypatch.setenv("TURNPROOF_PUBLIC_KEY", str(pub))
    data = tmp_path / "data"
    d = data / "runs" / RUN
    (d / "display").mkdir(parents=True)
    frames = {"f00010": 10, "f00020": 20}
    hashes = {fid: sha256_hex(_png(d / "display" / f"{fid}.png", i)) for fid, i in frames.items()}

    # overlay + occupancy, as the pipeline writes them
    ac = (20, 5, 280, 80)
    zones = {"forward_hold": (40, 40, 120, 110)}
    assert draw_overlay(
        d / "display" / "f00010.png",
        d / "display" / "f00010_overlay.png",
        ac,
        zones,
        [Det(10, 0, 50, 50, 100, 100, 300, 120, 0.9)],
        "forward_hold",
        0.3,
    )
    assert hashes["f00010"] == sha256_hex((d / "display" / "f00010.png").read_bytes())  # untouched
    series = [(f, 0.8 if f < 20 else 0.0, 0.9) for f in range(0, 40, 2)]
    hits = [
        MilestoneHit("loader_docked_start", 0, 0.9, True),
        MilestoneHit("loading_complete", 20, 0.9),
    ]
    write_occupancy(
        d, "forward_hold", series, {"forward_hold": [Cycle(0, 20, 0.9, True)]}, hits,
        fps=2.0, step=1, tau=0.3, n_frames=40, speed=1.0,
    )  # fmt: skip

    log = EventLog(d / "events.db", RUN)
    log.append("system", "ingested", {"frames": 40})
    log.append("system", "milestones_detected", {}, "OBSERVED", "CANDIDATE")
    log.append("system", "spark_evaluated", {"ok": True}, "CANDIDATE", "UNDER_REVIEW")
    head = log.head()

    milestones = [
        {"name": "loader_docked_start", "t_utc": "2026-10-30T17:58:00.000Z", "frame_index": 10,
         "method": "sam31_vehicle_zone_overlap_present_at_clip_start", "zone": "forward_hold",
         "confidence": 0.9, "evidence_frames": ["f00010"]},
        {"name": "loading_complete", "t_utc": "2026-10-30T18:01:30.000Z", "frame_index": 20,
         "method": "sam31_vehicle_zone_overlap", "zone": "forward_hold", "confidence": 0.87,
         "evidence_frames": ["f00020"]},
    ]  # fmt: skip
    claim = {
        "delay_code": "32",
        "minutes": 9,
        "source": "synthetic",
        "claim_window_utc": {"start": "2026-10-30T18:05:00Z", "end": "2026-10-30T18:14:00Z"},
    }
    rows = [
        {"milestone": "loading_complete", "video_utc": "2026-10-30T18:01:30.000Z",
         "handler_log_utc": "2026-10-30T18:04:00Z", "video_minus_log_min": -2.5, "note": None,
         "airline_claim_minutes": 9, "video_supported_minutes": 0, "delta_min": 9},
    ]  # fmt: skip
    proposed = {
        "delay_code_family": "none",
        "minutes_supported_by_video": 0,
        "basis": "before window",
    }
    ev = [
        {"id": fid, "t_utc": "2026-10-30T18:00:00.000Z", "frame_index": i, "sha256_original": "0" * 64,
         "sha256_redacted": hashes[fid], "redaction": "no_person_detected", "original_ref": "none"}
        for fid, i in frames.items()
    ]  # fmt: skip
    meta = {"station": "BLR", "stand": "D14", "flight_number": "XY123", "flight_date": "2026-10-30",
            "airline": "XY Airways", "handler": "Handler Co", "camera_id": "cam"}  # fmt: skip
    spark = {"id": "muse-spark-1.3", "prompt_version": "kf-0.3", "prompt_sha256": "c" * 64,
             "reasoning_effort": "medium", "path": "json_schema", "ok": True,
             "rule_claim_check": {"claim": "loader_departed", "agree": True, "reason": "gone"},
             "hold_door_state": "unknown", "requires_operator_review": True, "confidence": 0.8}  # fmt: skip
    models = {"sam": {"id": "sam-3.1", "prompts": ["aircraft", "vehicle", "person"], "calls": []},
              "spark": spark, "asr": None, "zones_config_sha256": "b" * 64}  # fmt: skip
    p = packet_mod.build(
        packet_id=PID, clip_meta=meta,
        source={"type": "upload", "camera_id": "cam", "file_sha256": "a" * 64, "fps": 2.0, "duration_s": 20.0},
        time_sync={"status": "declared", "reference_start_utc": "2026-10-30T17:58:00Z",
                   "measured_offset_s": None, "speed_factor": 1.0, "speed_factor_source": "estimated",
                   "method": "declared"},
        airline_claim=claim, handler_log=[{"milestone": "loading_complete", "t_utc": "2026-10-30T18:04:00Z"}],
        milestones=milestones, observed_facts=[{"text": "loader gone", "frames": ["f00020"], "source": "spark"}],
        discrepancies=rows, proposed=proposed, evidence_frames=ev, models=models, chain_head=head,
    )  # fmt: skip
    p = packet_mod.sign_and_write(p, d / "packets" / f"{PID}.json", "k")
    log.append("system", "packet_built", {"packet_id": PID})
    log.export_jsonl(d / "eventlog.jsonl")

    metrics = {"run_id": RUN, "clip": "clips/clipx.mp4", "frames_processed": 40, "sam_requests": 3,
               "sam_requests_live": 0, "spark_calls": 1, "spark_tokens_in": 10, "spark_tokens_out": 5,
               "est_cost_usd": 0.0, "latency_s": {"total_s": 1.0}}  # fmt: skip
    (d / "run_metrics.json").write_text(json.dumps(metrics))
    summary = {
        "run_id": RUN, "status": "candidate", "zone_used": "forward_hold", "view": "front_quarter",
        "zones_frame0": {}, "cycles": {}, "time_sync": p["time_sync"], "milestones": milestones,
        "spark": spark, "observed_facts": p["observed_facts"], "discrepancies": rows,
        "proposed_claim": proposed, "packet": str(d / "packets" / f"{PID}.json"), "packet_id": PID,
        "packet_sha256": p["packet_sha256"], "clip": "clips/clipx.mp4", "clip_meta": meta,
        "airline_claim": claim, "handler_log": p["handler_log"], "evidence_frames": ev,
        "overlays": {"f00010": "display/f00010_overlay.png"}, "keyframe_ids": ["f00020"],
        "source": {"file_sha256": "a" * 64, "fps": 2.0, "duration_s": 20.0},
        "metrics": metrics, "created_at_utc": "2026-11-01T10:00:00Z",
    }  # fmt: skip
    (d / "run_summary.json").write_text(json.dumps(summary))
    monkeypatch.setattr(app_mod, "store", RunStore(data))
    return d


def test_console_end_to_end(run_dir):
    c = TestClient(app_mod.app)
    r = c.get("/")
    assert r.status_code == 200 and RUN in r.text and "XY123" in r.text

    r = c.get(f"/runs/{RUN}")
    assert r.status_code == 200
    assert "loading_complete" in r.text and "agrees with the rule" in r.text
    assert "f00010_overlay.png" in r.text  # overlay used where it exists
    assert 'name="action" value="confirm"' in r.text

    # confirm without a note is refused (flagged for review) ...
    r = c.post(
        f"/runs/{RUN}/action", data={"action": "confirm", "note": ""}, follow_redirects=False
    )
    assert r.status_code == 303 and "err=" in r.headers["location"]
    assert app_mod.store.review(RUN)["state"] == "UNDER_REVIEW"
    # ... and accepted with one
    c.post(f"/runs/{RUN}/action", data={"action": "confirm", "note": "checked frames"})
    assert app_mod.store.review(RUN)["state"] == "CONFIRMED"
    c.post(f"/runs/{RUN}/action", data={"action": "send"})
    assert app_mod.store.review(RUN)["state"] == "SENT"

    # the decisions are in the hash-chained log, after the packet_built row; sending re-issues
    # the packet with the decision inside and the draft's hash in the chain
    ev = app_mod.store.events(RUN)
    assert [e["action"] for e in ev[-3:]] == ["confirm", "send", "packet_reissued"]
    assert ev[-1]["prev_hash"] == ev[-2]["hash"]
    sent = app_mod.store.packet(RUN)
    draft = json.loads((run_dir / "packets" / f"{PID}.draft.json").read_text())
    assert sent["review"]["decision"] == "confirmed" and sent["review"]["note"] == "checked frames"
    assert sent["chain"]["prev_packet_sha256"] == draft["packet_sha256"]
    assert sent["packet_sha256"] != draft["packet_sha256"]

    # airline side
    c.get("/role/airline")
    r = c.get(f"/packets/{PID}")
    assert r.status_code == 200 and 'value="acknowledge"' in r.text and 'value="dispute"' in r.text
    r = c.post(
        f"/packets/{PID}/action", data={"action": "dispute", "note": ""}, follow_redirects=False
    )
    assert "err=" in r.headers["location"]
    c.post(f"/packets/{PID}/action", data={"action": "acknowledge"})
    assert app_mod.store.review(RUN)["state"] == "ACKNOWLEDGED"
    acked = app_mod.store.packet(RUN)
    assert acked["counterparty"]["state"] == "ACKNOWLEDGED"
    assert acked["chain"]["prev_packet_sha256"] == sent["packet_sha256"]  # version chain

    # verifier from the UI still passes after the extra log rows (chain head is mid-chain)
    v = c.post(f"/api/packets/{PID}/verify").json()
    assert v["ok"] is True, v["output"]
    assert "RESULT: VERIFIED" in v["output"]

    # downloads and files
    assert c.get(f"/packets/{PID}.json").json()["packet_id"] == PID
    pdf = c.get(f"/packets/{PID}.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert c.get(f"/files/{RUN}/display/f00010_overlay.png").status_code == 200
    assert c.get(f"/files/{RUN}/display/../events.db").status_code in (404, 400)
    assert c.get("/runs/nope").status_code == 404
    assert c.get(f"/metrics/{RUN}").json()["frames_processed"] == 40


def test_actions_follow_roles(run_dir):
    s = app_mod.store
    assert s.available_actions(RUN, "handler") == ["confirm", "reject", "correct"]
    assert s.available_actions(RUN, "airline") == []
    s.transition(RUN, "handler", "reject", "second vehicle, not the loader")
    assert s.review(RUN)["state"] == "REJECTED"
    assert s.available_actions(RUN, "handler") == []


def test_statement_goes_into_the_reissued_packet(run_dir):
    s = app_mod.store
    s.set_statement(RUN, {"text": "Loader left at 18:01; second vehicle was the catering truck.",
                          "source": "typed", "model": None, "audio_sha256": None,
                          "recorded_at_utc": "2026-11-01T10:00:00Z", "operator": "handler_operator"})  # fmt: skip
    s.transition(RUN, "handler", "confirm", "ok")
    s.transition(RUN, "handler", "send")
    p = s.packet(RUN)
    assert p["human_statement"]["text"].startswith("Loader left")
    assert [e["action"] for e in s.events(RUN)][-4:] == [
        "statement_recorded", "confirm", "send", "packet_reissued"
    ]  # fmt: skip


def test_public_verify_page_with_zip_and_log(run_dir):
    import io
    import zipfile

    c = TestClient(app_mod.app)
    assert c.get("/verify").status_code == 200
    # the frames zip the packet page offers, then the public page with it
    z = c.get(f"/packets/{PID}/frames.zip")
    assert z.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert "f00010.png" in names and "eventlog.jsonl" in names
    packet_bytes = (run_dir / "packets" / f"{PID}.json").read_bytes()
    log_bytes = (run_dir / "eventlog.jsonl").read_bytes()
    r = c.post(
        "/verify",
        files={
            "packet": ("p.json", packet_bytes, "application/json"),
            "frames": ("frames.zip", z.content, "application/zip"),
            "log": ("eventlog.jsonl", log_bytes, "text/plain"),
        },
    )
    assert r.status_code == 200 and "VERIFIED" in r.text and "RESULT: VERIFIED" in r.text
    # a tampered packet fails on the same page
    bad = packet_bytes.replace(b'"minutes": 9', b'"minutes": 19')
    assert bad != packet_bytes
    r = c.post("/verify", files={"packet": ("p.json", bad, "application/json")})
    assert "TAMPERED OR INVALID" in r.text
