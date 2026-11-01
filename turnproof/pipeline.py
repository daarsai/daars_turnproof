"""End-to-end run: clip -> frames (hashed, encrypted) -> SAM (aircraft, vehicle, person)
-> zones -> milestones -> Spark keyframe check -> discrepancy -> signed packet + event log.

API responses are cached per CLIP under data/cache/ (keyed by file sha256 + prompt), so
re-running a clip costs nothing.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2
import yaml

from turnproof.events.candidates import aircraft_box_for, best_zone, occupancy_series
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
from turnproof.review.overlay import write_occupancy, write_overlays
from turnproof.zones.aircraft_zones import all_zones

DATA = Path("data")
SCENARIOS = Path("scenarios")
CODE_FAMILIES = ["31", "32", "33", "34", "35", "36", "37", "38", "39", "none"]


def load_cfg(path: Path = Path("config/config.yaml")) -> dict:
    return yaml.safe_load(path.read_text())


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def ref_time(ref_start: str | None, video_s: float, speed: float | None) -> str | None:
    """Declared real-world time for a video offset. None unless both start and speed are declared."""
    if not ref_start or speed is None:
        return None
    t0 = datetime.fromisoformat(ref_start).astimezone(UTC)
    return (
        (t0 + timedelta(seconds=video_s * speed))
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def nearest(records: dict[int, dict], idx: int) -> dict:
    return records.get(idx) or records[min(records, key=lambda k: abs(k - idx))]


def zone_crop(
    frame_png: Path, zone: tuple, out_path: Path, pad: float = 0.25, scale: int = 2
) -> Path:
    """Crop the hold zone (padded) from a display frame and upscale it for the Spark door check."""
    img = cv2.imread(str(frame_png))
    h, w = img.shape[:2]
    x1, y1, x2, y2 = zone
    pw, ph = (x2 - x1) * pad, (y2 - y1) * pad
    x1, y1 = max(0, int(x1 - pw)), max(0, int(y1 - ph))
    x2, y2 = min(w, int(x2 + pw)), min(h, int(y2 + ph))
    crop = img[y1:y2, x1:x2]
    if crop.size:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        cv2.imwrite(str(out_path), crop)
    return out_path


def effective_cfg(cfg: dict, clip_cfg: dict) -> dict:
    """Apply the per-clip zone preset (side/nose) on top of the base config."""
    view = clip_cfg.get("view")
    presets = cfg.get("zone_presets", {})
    if view and view in presets:
        return {**cfg, "zones": presets[view]}
    return cfg


def run(
    clip: Path,
    cfg: dict,
    run_id: str | None = None,
    use_spark: bool = True,
) -> dict:
    t_start = time.time()
    run_id = run_id or f"{clip.stem}-{uuid.uuid4().hex[:8]}"
    out = DATA / "runs" / run_id
    out.mkdir(parents=True, exist_ok=True)
    clip_cfg = cfg.get("clips", {}).get(clip.stem, {}) or {}
    cfg = effective_cfg(cfg, clip_cfg)
    ref_start = clip_cfg.get("reference_start_utc")
    speed = clip_cfg.get("speed_factor")
    speed_src = clip_cfg.get("speed_factor_source")
    synced = bool(ref_start) and speed is not None
    nose_right = False  # zone presets are written per camera view; no mirroring needed
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

    # 2. perception (cached per clip) ----------------------------------------
    t = time.time()
    sam = SamClient(DATA / "cache" / "sam")
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
    zone_name, hits, cycles = best_zone(
        vehicles, aircraft, cfg, fps, nose_right, clip_cfg.get("zones_enabled"), speed
    )
    ab0 = aircraft_box_for(0, aircraft)
    zones0 = all_zones(ab0, cfg["zones"], nose_right) if ab0 else {}
    milestones: list[dict] = []
    for h in hits:
        rec = nearest(records, h.frame_index)
        milestones.append(
            {
                "name": h.name,
                "t_utc": rec["t_utc"],
                "frame_index": h.frame_index,
                "method": "sam31_vehicle_zone_overlap"
                + ("_present_at_clip_start" if h.present_at_clip_start else "")
                + ("_absence_cut_short_by_clip_end" if h.departure_at_clip_end else ""),
                "zone": zone_name,
                "confidence": h.confidence,
                "evidence_frames": [rec["id"]],
            }
        )
    timings["events_s"] = round(time.time() - t, 2)
    lc = next((m for m in milestones if m["name"] == "loading_complete"), None)
    if not lc:
        status = "no_candidate"
    elif not synced:
        status = "candidate_unsynced"
    else:
        status = "candidate"
    if lc:
        log.append(
            "system", "milestones_detected", {"milestones": milestones}, "OBSERVED", "CANDIDATE"
        )

    # 5. Spark keyframe check (full frames + zoomed hold crop) ----------------
    spark_result: dict = {"ok": False, "out": None, "path": "skipped"}
    observed_facts: list[dict] = []
    spark = SparkClient(
        DATA / "cache" / "spark", cfg["models"]["spark"], cfg["models"]["spark_reasoning_effort"]
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
        paths = [out / "display" / f"{k['id']}.png" for k in kf]
        ab_after = aircraft_box_for(after_idx, aircraft)
        if ab_after:
            zone_box = all_zones(ab_after, cfg["zones"], nose_right)[zone_name]
            crop = zone_crop(paths[2], zone_box, out / "display" / f"{kf[2]['id']}_holdcrop.png")
            paths.append(crop)
            keyframe_ids.append(f"{kf[2]['id']}_holdcrop")
        context = {
            "rule_claim": "loader_departed",
            "zone": zone_name,
            "milestones": [{k: m[k] for k in ("name", "t_utc", "frame_index")} for m in milestones],
            "airline_claim": {k: claim[k] for k in ("delay_code", "minutes", "source")},
            "allowed_code_families": CODE_FAMILIES,
            "images": [
                {"frame_id": fid, "shows": role}
                for fid, role in zip(
                    keyframe_ids,
                    [
                        "midway through the docked period",
                        "the frame where the rule says the equipment departed",
                        "three seconds of video later",
                        "zoomed crop of the hold area, three seconds of video later",
                    ],
                    strict=False,
                )
            ],
        }
        spark_result = spark.evaluate(paths, keyframe_ids, context)
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
    so = spark_result.get("out") or {}
    agrees = (so.get("rule_claim_check") or {}).get("agree") if so else None
    proposed = discrepancy.proposed_claim(
        claim, rows, has_loading_complete=bool(lc), synced=synced, spark_agrees=agrees
    )
    by_id = {r["id"]: r for r in records.values()}
    ev_ids = sorted(
        {fid for m in milestones for fid in m["evidence_frames"]}
        | {k for k in keyframe_ids if k in by_id}
    )
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

    # 6b. console artefacts: overlays (boxes drawn on COPIES of display frames) + occupancy ----
    t = time.time()
    tau = cfg["rules"]["docked_overlap_tau"]
    step = max(1, round(fps / float(cfg.get("sampling", {}).get("logic_fps", 2))))
    # a few extra context frames so the console can show the whole story, not only milestones
    n = max(records) + 1
    context_ids = [nearest(records, i)["id"] for i in (0, n // 4, n // 2, (3 * n) // 4, n - 1)]
    overlay_ids = sorted(set(ev_ids) | set(context_ids))
    overlays = write_overlays(
        out,
        overlay_ids,
        {r["id"]: r["frame_index"] for r in records.values()},
        aircraft,
        vehicles,
        cfg["zones"],
        zone_name,
        tau,
        nose_right,
    )
    write_occupancy(
        out,
        zone_name,
        occupancy_series(vehicles, aircraft, cfg["zones"], zone_name, nose_right, step=step),
        cycles,
        hits,
        fps=fps,
        step=step,
        tau=tau,
        n_frames=len(records),
        speed=speed,
    )
    timings["overlays_s"] = round(time.time() - t, 2)
    time_sync = {
        "status": "declared" if synced else "unsynced",
        "reference_start_utc": ref_start,
        "measured_offset_s": None,
        "speed_factor": speed,
        "speed_factor_source": speed_src,
        "method": (
            f"uploader_declared start; speed_factor {speed} ({speed_src}): 1 s video = {speed} s real"
            if synced
            else "unsynced: start time or speed factor not declared; no real-world minutes computed"
        ),
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
            "rule_claim_check": so.get("rule_claim_check"),
            "hold_door_state": so.get("hold_door_state"),
            "requires_operator_review": so.get("requires_operator_review", True),
            "confidence": so.get("confidence"),
            # a NOTE only: the packet's proposed_claim never reads this field
            "suggested_delay_code_family": so.get("candidate_delay_code_family"),
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
    log.export_jsonl(out / "eventlog.jsonl")

    # 7. metrics --------------------------------------------------------------
    live_sam = [c for c in sam.calls if not c.get("cached")]
    sam_frames = len(live_sam) * max(50, len(records))
    tokens_in = sum(c.get("tokens_in", 0) for c in spark.calls)
    tokens_out = sum(c.get("tokens_out", 0) for c in spark.calls)
    metrics = {
        "run_id": run_id,
        "clip": str(clip),
        "frames_processed": len(records),
        "sam_requests": len(sam.calls),
        "sam_requests_live": len(live_sam),
        "sam_frames_billed_est": sam_frames,
        "spark_calls": len(spark.calls),
        "spark_tokens_in": tokens_in,
        "spark_tokens_out": tokens_out,
        "est_cost_usd": round(sam_frames * 0.0002 + tokens_in * 1.25e-6 + tokens_out * 4.25e-6, 4),
        "latency_s": {**timings, "total_s": round(time.time() - t_start, 2)},
        "candidates": 1 if lc else 0,
        "cycles_per_zone": {z: len(c) for z, c in cycles.items()},
        "milestones_found": [m["name"] for m in milestones],
        "time_sync_status": time_sync["status"],
    }
    (out / "run_metrics.json").write_text(json.dumps(metrics, indent=1))

    summary = {
        "run_id": run_id,
        "status": status,
        "zone_used": zone_name,
        "view": clip_cfg.get("view", "side"),
        "zones_frame0": zones0,
        "cycles": {
            z: [{"start": c.start, "end": c.end, "conf": c.conf} for c in cs]
            for z, cs in cycles.items()
        },
        "time_sync": time_sync,
        "milestones": milestones,
        "spark": models["spark"],
        "observed_facts": observed_facts,
        "discrepancies": rows,
        "proposed_claim": proposed,
        "packet": str(packet_path) if packet_path else None,
        "packet_id": packet["packet_id"] if packet else None,
        "packet_sha256": packet["packet_sha256"] if packet else None,
        "clip": str(clip),
        "clip_meta": clip_meta,
        "airline_claim": claim,
        "handler_log": handler_log,
        "evidence_frames": evidence_frames,
        "overlays": overlays,
        "keyframe_ids": keyframe_ids,
        "source": {"file_sha256": info.sha256, "fps": fps, "duration_s": round(info.duration_s, 2)},
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
    r.add_argument("--no-spark", action="store_true", help="skip the Muse Spark keyframe check")
    rp = sub.add_parser(
        "replay", help="re-run the clip of an existing run (API responses come from the cache)"
    )
    rp.add_argument("run_id")
    a = ap.parse_args(argv)
    if a.cmd == "replay":
        prev = json.loads((DATA / "runs" / a.run_id / "run_metrics.json").read_text())
        a.clip, a.run_id, a.no_spark = prev["clip"], None, False
        a.cmd = "run"
    if a.cmd == "run":
        os.environ.setdefault("PYTHONUNBUFFERED", "1")
        s = run(Path(a.clip), load_cfg(), a.run_id, not a.no_spark)
        keys = (
            "run_id", "status", "view", "zone_used", "cycles", "time_sync", "milestones", "spark",
            "observed_facts", "discrepancies", "proposed_claim", "packet", "packet_sha256",
        )  # fmt: skip
        show = {k: s[k] for k in keys}
        show["latency_s"] = s["metrics"]["latency_s"]
        show["est_cost_usd"] = s["metrics"]["est_cost_usd"]
        print(json.dumps(show, indent=1))
        print(f"run folder: data/runs/{s['run_id']}")
        print(f"console:    make serve  ->  http://localhost:8080/runs/{s['run_id']}")
        if s["packet"]:
            print(
                f"verify:  python verify_packet.py {s['packet']} --frames data/runs/{s['run_id']}/display"
                f" --log data/runs/{s['run_id']}/eventlog.jsonl"
            )
