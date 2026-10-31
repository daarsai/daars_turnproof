"""End-to-end run: clip -> frames (hashed, encrypted) -> SAM (aircraft, vehicle, person)
-> zones -> milestones -> candidate + event log. Spark, discrepancy and packet come next."""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import yaml

from turnproof.events.candidates import aircraft_box_for, best_zone
from turnproof.events.eventlog import EventLog
from turnproof.ingest.crypto import load_data_key
from turnproof.ingest.frames import ensure_h264, extract, probe
from turnproof.ingest.redact import redact_display_frames
from turnproof.perception.sam_client import SamClient
from turnproof.perception.sam_parse import parse
from turnproof.zones.aircraft_zones import all_zones

DATA = Path("data")


def load_cfg(path: Path = Path("config/config.yaml")) -> dict:
    return yaml.safe_load(path.read_text())


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def run(clip: Path, cfg: dict, run_id: str | None = None, nose_left: bool = False) -> dict:
    t_start = time.time()
    run_id = run_id or f"{clip.stem}-{uuid.uuid4().hex[:8]}"
    out = DATA / "runs" / run_id
    out.mkdir(parents=True, exist_ok=True)
    clip_cfg = cfg.get("clips", {}).get(clip.stem, {}) or {}
    ref_start = clip_cfg.get("reference_start_utc")
    log = EventLog(out / "events.db", run_id)
    timings: dict[str, float] = {}

    # 1. ingest
    t = time.time()
    info = probe(clip)
    h264 = ensure_h264(clip, out / "input_h264.mp4")
    try:
        key = load_data_key()
    except RuntimeError:
        key = None
    records = extract(h264, out, key, ref_start, every=1)
    timings["ingest_s"] = round(time.time() - t, 2)
    log.append("system", "ingested", {"clip_sha256": info.sha256, "frames": len(records)})

    # 2. perception (cached)
    t = time.time()
    sam = SamClient(out / "api" / "sam")
    aircraft = parse(sam.segment_video(h264, "aircraft"))
    vehicles = parse(sam.segment_video(h264, "vehicle"))
    persons = parse(sam.segment_video(h264, "person"))
    timings["sam_s"] = round(time.time() - t, 2)
    (out / "detections.json").write_text(
        json.dumps(
            {
                "aircraft_frames": len(aircraft),
                "vehicle_frames": len(vehicles),
                "person_frames": len(persons),
                "calls": sam.calls,
            },
            indent=1,
        )
    )

    # 3. redaction (hash of redacted display frames)
    t = time.time()
    records = redact_display_frames(out, persons, records)
    timings["redact_s"] = round(time.time() - t, 2)

    # 4. zones + milestones
    t = time.time()
    zone_name, hits = best_zone(vehicles, aircraft, cfg, nose_left)
    ab0 = aircraft_box_for(0, aircraft)
    zones0 = all_zones(ab0, cfg["zones"], nose_left) if ab0 else {}
    timings["events_s"] = round(time.time() - t, 2)

    fps = info.fps
    milestones = []
    for h in hits:
        rec = (
            records.get(h.frame_index)
            or records[min(records, key=lambda k: abs(k - h.frame_index))]
        )
        milestones.append(
            {
                "name": h.name,
                "t_utc": rec["t_utc"],
                "t_raw_s": round(h.frame_index / fps, 2),
                "frame_index": h.frame_index,
                "method": "sam31_vehicle_zone_overlap",
                "zone": zone_name,
                "confidence": h.confidence,
                "evidence_frames": [rec["id"]],
            }
        )
    status = (
        "candidate" if any(m["name"] == "loading_complete" for m in milestones) else "no_candidate"
    )
    if status == "candidate":
        log.append(
            "system", "milestones_detected", {"milestones": milestones}, "OBSERVED", "CANDIDATE"
        )

    summary = {
        "run_id": run_id,
        "clip": str(clip),
        "clip_sha256": info.sha256,
        "fps": fps,
        "duration_s": round(info.duration_s, 2),
        "time_sync": {
            "status": "declared" if ref_start else "unsynced",
            "reference_start_utc": ref_start,
            "method": "uploader_declared" if ref_start else None,
        },
        "zone_used": zone_name,
        "zones_frame0": zones0,
        "milestones": milestones,
        "status": status,
        "timings": {**timings, "total_s": round(time.time() - t_start, 2)},
        "sam_calls": sam.calls,
        "event_log_head": log.head(),
        "created_at_utc": now(),
    }
    (out / "run_summary.json").write_text(json.dumps(summary, indent=1))
    log.export_jsonl(out / "eventlog.jsonl")
    return summary


def main(argv: list[str] | None = None) -> None:
    import argparse

    ap = argparse.ArgumentParser(prog="turnproof")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the pipeline on a clip")
    r.add_argument("clip")
    r.add_argument("--run-id")
    r.add_argument("--nose-left", action="store_true", help="aircraft nose points left in frame")
    a = ap.parse_args(argv)
    if a.cmd == "run":
        os.environ.setdefault("PYTHONUNBUFFERED", "1")
        s = run(Path(a.clip), load_cfg(), a.run_id, a.nose_left)
        print(
            json.dumps(
                {k: s[k] for k in ("run_id", "status", "zone_used", "milestones", "timings")},
                indent=1,
            )
        )
        print(f"run folder: data/runs/{s['run_id']}")
