"""End-to-end run: clip -> frames (hashed, encrypted) -> SAM (aircraft, vehicle, person)
-> zones -> milestones -> Spark keyframe check -> discrepancy -> signed packet + event log."""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from turnproof.events.candidates import aircraft_box_for, best_zone
from turnproof.events.eventlog import EventLog
from turnproof.evidence import discrepancy
from turnproof.evidence import packet as packet_mod
from turnproof.evidence.canonical import sha256_hex
from turnproof.ingest.crypto import load_data_key
from turnproof.ingest.frames import ensure_h264, extract, probe
from turnproof.ingest.redact import redact_display_frames
from turnproof.perception.sam_client import SamClient
from turnproof.perception.sam_parse import parse
from turnproof.reason.spark_client import SparkClient
from turnproof.zones.aircraft_zones import all_zones

DATA = Path("data")
SCENARIOS = Path("scenarios")


def load_cfg(path: Path = Path("config/config.yaml")) -> dict:
    return yaml.safe_load(path.read_text())


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def ref_time(ref_start: str | None, video_s: float, speed: float) -> str | None:
    """Declared real-world time for a video offset, applying the declared speed factor."""
    if not ref_start:
        return None
    t0 = datetime.fromisoformat(ref_start).astimezone(UTC)
    t = t0 + timedelta(seconds=video_s * speed)
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def nearest(records: dict[int, dict], idx: int) -> dict:
    return records.get(idx) or records[min(records, key=lambda k: abs(k - idx))]


def run(
    clip: Path,
    cfg: dict,
    run_id: str | None = None,
    nose_left: bool = False,
    use_spark: bool = True,
) -> dict:
    t_start = time.time()
    run_id = run_id or f"{clip.stem}-{uuid.uuid4().hex[:8]}"
    out = DATA / "runs" / run_id
    out.mkdir(parents=True, exist_ok=True)
    clip_cfg = cfg.get("clips", {}).get(clip.stem, {}) or {}
    ref_start = clip_cfg.get("reference_start_utc")
    speed = float(clip_cfg.get("speed_factor", 1.0))
    scen = SCENARIOS / clip.stem
    clip_meta = json.loads((scen / "clip_meta.json").read_text())
    claim = discrepancy.load_claim(scen / "airline_claim.json")
    handler_log = discrepancy.load_handler_log(scen / "handler_log.csv")
    log = EventLog(out / "events.db", run_id)
    timings: dict[str, float] = {}

    # 1. ingest ---------------------------------------------------------------
    t = time.time()
    info = probe(clip)
    h264 = ensure_h264(clip, out / "input_h264.mp4")
    try:
        key = load_data_key()
    except RuntimeError:
        key = None
    records = extract(h264, out, key, None, every=1)
    fps = info.fps
    for idx, rec in records.items():
        rec["t_utc"] = ref_time(ref_start, idx / fps, speed)
    timings["ingest_s"] = round(time.time() - t, 2)
    log.append("system", "ingested", {"clip_sha256": info.sha256, "frames": len(records)})

    # 2. perception (cached) --------------------------------------------------
    t = time.time()
    sam = SamClient(out / "api" / "sam")
    aircraft = parse(sam.segment_video(h264, "aircraft"))
    vehicles = parse(sam.segment_video(h264, "vehicle"))
    persons = parse(sam.segment_video(h264, "person"))
    timings["sam_s"] = round(time.time() - t, 2)
    log.append("system", "sam_segmented", {"calls": sam.calls})

    # 3. redaction ------------------------------------------------------------
    t = time.time()
    records = redact_display_frames(out, persons, records)
    timings["redact_s"] = round(time.time() - t, 2)

    # 4. zones + milestones ---------------------------------------------------
    t = time.time()
    zone_name, hits = best_zone(vehicles, aircraft, cfg, nose_left)
    ab0 = aircraft_box_for(0, aircraft)
    zones0 = all_zones(ab0, cfg["zones"], nose_left) if ab0 else {}
    milestones: list[dict] = []
    for h in hits:
        rec = nearest(records, h.frame_index)
        milestones.append(
            {
                "name": h.name,
                "t_utc": rec["t_utc"],
                "frame_index": h.frame_index,
                "method": "sam31_vehicle_zone_overlap"
                + ("_present_at_clip_start" if h.present_at_clip_start else ""),
                "zone": zone_name,
                "confidence": h.confidence,
                "evidence_frames": [rec["id"]],
            }
        )
    timings["events_s"] = round(time.time() - t, 2)
    lc = next((m for m in milestones if m["name"] == "loading_complete"), None)
    status = "candidate" if lc else "no_candidate"
    if lc:
        log.append(
            "system", "milestones_detected", {"milestones": milestones}, "OBSERVED", "CANDIDATE"
        )

    # 5. Spark keyframe check -------------------------------------------------
    spark_result: dict = {"ok": False, "out": None, "path": "skipped"}
    observed_facts: list[dict] = []
    spark = SparkClient(
        out / "api" / "spark", cfg["models"]["spark"], cfg["models"]["spark_reasoning_effort"]
    )
    keyframe_ids: list[str] = []
    if lc and use_spark:
        t = time.time()
        docked = next((m for m in milestones if m["name"] == "loader_docked_start"), None)
        mid_idx = (
            (docked["frame_index"] + lc["frame_index"]) // 2
            if docked
            else max(0, lc["frame_index"] - int(5 * fps))
        )
        after_idx = min(max(records), lc["frame_index"] + int(3 * fps))
        kf = [nearest(records, i) for i in (mid_idx, lc["frame_index"], after_idx)]
        keyframe_ids = [k["id"] for k in kf]
        context = {
            "rule_claim": "loader_departed",
            "zone": zone_name,
            "milestones": [{k: m[k] for k in ("name", "t_utc", "frame_index")} for m in milestones],
            "airline_claim": {k: claim[k] for k in ("delay_code", "minutes", "source")},
            "allowed_code_families": ["31", "32", "33", "34", "35", "36", "37", "38", "39", "none"],
            "keyframe_roles": [
                "during loading",
                "at loading_complete",
                "3 s after loading_complete",
            ],
        }
        spark_result = spark.evaluate(
            [out / "display" / f"{k['id']}.png" for k in kf], keyframe_ids, context
        )
        timings["spark_s"] = round(time.time() - t, 2)
        log.append(
            "system",
            "spark_evaluated",
            {"ok": spark_result["ok"], "path": spark_result["path"]},
            "CANDIDATE",
            "UNDER_REVIEW",
        )
        if spark_result["ok"]:
            so = spark_result["out"]
            observed_facts = [
                {"text": f["text"], "frames": f["frames"], "source": cfg["models"]["spark"]}
                for f in so["observed_facts"]
            ]
            if so["hold_door_state"] == "closed":
                milestones.append(
                    {
                        "name": "hold_door_closed",
                        "t_utc": kf[2]["t_utc"],
                        "frame_index": after_idx,
                        "method": "spark_keyframe",
                        "zone": zone_name,
                        "confidence": so["confidence"],
                        "evidence_frames": [kf[2]["id"]],
                    }
                )

    # 6. discrepancy + packet -------------------------------------------------
    rows = discrepancy.build(milestones, handler_log, claim)
    family = (spark_result.get("out") or {}).get("candidate_delay_code_family") or str(
        claim["delay_code"]
    )[:2]
    proposed = discrepancy.proposed_claim(claim, rows, family if family != "none" else "none")
    ev_ids = sorted({fid for m in milestones for fid in m["evidence_frames"]} | set(keyframe_ids))
    by_id = {r["id"]: r for r in records.values()}
    evidence_frames = [
        {
            "id": fid,
            "t_utc": by_id[fid]["t_utc"],
            "frame_index": by_id[fid]["frame_index"],
            "sha256_original": by_id[fid]["sha256_original"],
            "sha256_redacted": by_id[fid]["sha256_redacted"],
            "redaction": by_id[fid]["redaction"],
            "original_ref": by_id[fid]["original_ref"] or "none",
        }
        for fid in ev_ids
    ]
    time_sync = {
        "status": "declared" if ref_start else "unsynced",
        "reference_start_utc": ref_start,
        "measured_offset_s": None,
        "method": f"uploader_declared; speed_factor={speed} (1 s video = {speed} s real)"
        if ref_start
        else "none",
    }
    models = {
        "sam": {
            "id": cfg["models"]["sam"],
            "prompts": ["aircraft", "vehicle", "person"],
            "calls": sam.calls,
        },
        "spark": {
            "id": cfg["models"]["spark"],
            "prompt_version": spark.prompt_version,
            "prompt_sha256": spark.prompt_sha256,
            "reasoning_effort": cfg["models"]["spark_reasoning_effort"],
            "path": spark_result.get("path"),
            "ok": spark_result.get("ok"),
            "rule_claim_check": (spark_result.get("out") or {}).get("rule_claim_check"),
            "hold_door_state": (spark_result.get("out") or {}).get("hold_door_state"),
            "requires_operator_review": (spark_result.get("out") or {}).get(
                "requires_operator_review", True
            ),
            "confidence": (spark_result.get("out") or {}).get("confidence"),
        },
        "asr": None,
        "zones_config_sha256": sha256_hex(json.dumps(cfg["zones"], sort_keys=True).encode()),
    }
    packet_path = None
    packet = None
    if lc:
        pid = f"TP-{datetime.now(UTC):%Y%m%d}-{run_id[-8:]}"
        packet = packet_mod.build(
            packet_id=pid,
            clip_meta=clip_meta,
            source={
                "type": "upload",
                "camera_id": clip_meta["camera_id"],
                "file_sha256": info.sha256,
                "fps": fps,
                "duration_s": round(info.duration_s, 2),
            },
            time_sync=time_sync,
            airline_claim=claim,
            handler_log=handler_log,
            milestones=milestones,
            observed_facts=observed_facts,
            discrepancies=rows,
            proposed=proposed,
            evidence_frames=evidence_frames,
            models=models,
            chain_head=log.head(),
        )
        packet_path = out / "packets" / f"{pid}.json"
        packet = packet_mod.sign_and_write(packet, packet_path, cfg["integrity"]["key_id"])
        log.append(
            "system", "packet_built", {"packet_id": pid, "packet_sha256": packet["packet_sha256"]}
        )
        log.export_jsonl(
            out / "eventlog.jsonl"
        )  # chain head inside packet = head before packet_built
    else:
        log.export_jsonl(out / "eventlog.jsonl")

    # 7. metrics --------------------------------------------------------------
    sam_frames = sum(1 for _ in range(0))  # placeholder replaced below
    sam_frames = 3 * max(50, len(records)) if any(not c.get("cached") for c in sam.calls) else 0
    tokens_in = sum(c.get("tokens_in", 0) for c in spark.calls)
    tokens_out = sum(c.get("tokens_out", 0) for c in spark.calls)
    metrics = {
        "run_id": run_id,
        "clip": str(clip),
        "frames_processed": len(records),
        "sam_requests": len(sam.calls),
        "sam_frames_billed_est": sam_frames,
        "spark_calls": len(spark.calls),
        "spark_tokens_in": tokens_in,
        "spark_tokens_out": tokens_out,
        "est_cost_usd": round(sam_frames * 0.0002 + tokens_in * 1.25e-6 + tokens_out * 4.25e-6, 4),
        "latency_s": {**timings, "total_s": round(time.time() - t_start, 2)},
        "candidates": 1 if lc else 0,
        "milestones_found": [m["name"] for m in milestones],
        "time_sync_status": time_sync["status"],
        "hash_verification": "pending_verify_packet",
    }
    (out / "run_metrics.json").write_text(json.dumps(metrics, indent=1))

    summary = {
        "run_id": run_id,
        "status": status,
        "zone_used": zone_name,
        "zones_frame0": zones0,
        "time_sync": time_sync,
        "milestones": milestones,
        "spark": models["spark"],
        "observed_facts": observed_facts,
        "discrepancies": rows,
        "proposed_claim": proposed,
        "packet": str(packet_path) if packet_path else None,
        "packet_sha256": packet["packet_sha256"] if packet else None,
        "metrics": metrics,
        "created_at_utc": now(),
    }
    (out / "run_summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def main(argv: list[str] | None = None) -> None:
    import argparse

    ap = argparse.ArgumentParser(prog="turnproof")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the pipeline on a clip (scenarios/<clip>/ must exist)")
    r.add_argument("clip")
    r.add_argument("--run-id")
    r.add_argument("--nose-left", action="store_true", help="aircraft nose points left in frame")
    r.add_argument("--no-spark", action="store_true", help="skip the Muse Spark keyframe check")
    a = ap.parse_args(argv)
    if a.cmd == "run":
        os.environ.setdefault("PYTHONUNBUFFERED", "1")
        s = run(Path(a.clip), load_cfg(), a.run_id, a.nose_left, not a.no_spark)
        show = {
            k: s[k]
            for k in (
                "run_id",
                "status",
                "zone_used",
                "milestones",
                "spark",
                "discrepancies",
                "proposed_claim",
                "packet",
                "packet_sha256",
            )
        }
        show["latency_s"] = s["metrics"]["latency_s"]
        show["est_cost_usd"] = s["metrics"]["est_cost_usd"]
        print(json.dumps(show, indent=1))
        print(f"run folder: data/runs/{s['run_id']}")
        if s["packet"]:
            print(
                f"verify:  python verify_packet.py {s['packet']} --frames data/runs/{s['run_id']}/display --log data/runs/{s['run_id']}/eventlog.jsonl"
            )
