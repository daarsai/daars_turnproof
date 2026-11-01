"""Background runs started from the console (upload form or POST /api/upload).

One thread per run. State lives in data/runs/<run_id>/status.json so the console can show
progress and survive a page reload; the pipeline writes run_summary.json when it finishes.
"""

from __future__ import annotations

import json
import threading
import traceback
import uuid
from datetime import UTC, datetime
from pathlib import Path

from turnproof import pipeline

VIEWS = ("front_quarter", "side", "nose")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_status(run_dir: Path, **fields) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    p = run_dir / "status.json"
    cur = json.loads(p.read_text()) if p.exists() else {}
    cur.update(fields, updated_at_utc=_now())
    p.write_text(json.dumps(cur, indent=1))


def read_status(run_dir: Path) -> dict | None:
    p = run_dir / "status.json"
    return json.loads(p.read_text()) if p.exists() else None


def write_scenario(dir_: Path, meta: dict, claim: dict, log: list[dict]) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / "clip_meta.json").write_text(json.dumps(meta, indent=1))
    (dir_ / "airline_claim.json").write_text(json.dumps(claim, indent=1))
    lines = ["milestone,t_utc"] + [f"{e['milestone']},{e['t_utc']}" for e in log]
    (dir_ / "handler_log.csv").write_text("\n".join(lines) + "\n")
    return dir_


def start_run(
    clip: Path,
    *,
    clip_cfg: dict,
    scenario_dir: Path,
    data_dir: Path,
    use_spark: bool = True,
    run_id: str | None = None,
) -> str:
    run_id = run_id or f"{clip.stem}-{uuid.uuid4().hex[:8]}"
    run_dir = data_dir / "runs" / run_id
    write_status(
        run_dir,
        run_id=run_id,
        state="queued",
        stage="queued",
        clip=str(clip),
        clip_cfg=clip_cfg,
        started_at_utc=_now(),
        error=None,
    )

    def job() -> None:
        write_status(run_dir, state="running")
        try:
            pipeline.run(
                clip,
                pipeline.load_cfg(),
                run_id,
                use_spark,
                clip_cfg=clip_cfg,
                scenario_dir=scenario_dir,
                progress=lambda stage: write_status(run_dir, stage=stage),
            )
            write_status(run_dir, state="done", stage="done", finished_at_utc=_now())
        except Exception as e:  # noqa: BLE001 - the console must show whatever went wrong
            write_status(
                run_dir,
                state="failed",
                stage="failed",
                error=f"{type(e).__name__}: {e}",
                traceback=traceback.format_exc()[-4000:],
                finished_at_utc=_now(),
            )

    threading.Thread(target=job, name=f"turnproof-{run_id}", daemon=True).start()
    return run_id


def start_capture_run(
    *,
    camera,
    flight,
    seconds: float,
    scenario_dir: Path,
    data_dir: Path,
    event: str = "loading",
    use_spark: bool = True,
) -> str:
    """Record `seconds` from the stand camera, then run the pipeline on the recording.
    The declared clip start is the flight's on-block time from the feed (the capture starts
    there); the speed factor is the camera's (1.0 for a real camera)."""
    from turnproof.ingest import camera as cam_mod

    stem = "".join(
        ch if ch.isalnum() else "-" for ch in f"{flight.flight_number}-{camera.stand}"
    ).lower()
    run_id = f"{stem}-{uuid.uuid4().hex[:8]}"
    run_dir = data_dir / "runs" / run_id
    clip = data_dir / "captures" / f"{run_id}.mp4"
    clip_cfg = {
        "reference_start_utc": flight.on_block_utc,
        "speed_factor": float(camera.speed_factor),
        "speed_factor_source": camera.speed_factor_source,
        "view": camera.view,
        "event": event,
    }
    write_status(
        run_dir,
        run_id=run_id,
        state="recording",
        stage=f"recording: {seconds:.0f} s from {camera.id} ({cam_mod.redact_url(camera.url)})",
        clip=str(clip),
        clip_cfg=clip_cfg,
        capture={
            "camera_id": camera.id,
            "stand": camera.stand,
            "flight_number": flight.flight_number,
            "flight_date": flight.flight_date,
            "on_block_utc": flight.on_block_utc,
            "off_block_utc": flight.off_block_utc,
            "seconds": seconds,
            "source": flight.source,
        },
        started_at_utc=_now(),
        error=None,
    )

    def job() -> None:
        try:
            cam_mod.record(camera.url, seconds, clip)
            write_status(run_dir, state="running", stage="ingest: recording done")
            pipeline.run(
                clip,
                pipeline.load_cfg(),
                run_id,
                use_spark,
                clip_cfg=clip_cfg,
                scenario_dir=scenario_dir,
                progress=lambda stage: write_status(run_dir, stage=stage),
            )
            write_status(run_dir, state="done", stage="done", finished_at_utc=_now())
        except Exception as e:  # noqa: BLE001 - the console must show whatever went wrong
            write_status(
                run_dir,
                state="failed",
                stage="failed",
                error=f"{type(e).__name__}: {e}",
                traceback=traceback.format_exc()[-4000:],
                finished_at_utc=_now(),
            )

    threading.Thread(target=job, name=f"turnproof-capture-{run_id}", daemon=True).start()
    return run_id
