"""TurnProof review console (FastAPI + Jinja2, no build step).

Two roles, switched with the toggle in the header (demo only; no login):
  handler  - sees runs, evidence, the Spark keyframe check; confirms / rejects / corrects; sends
  airline  - sees sent packets; verifies, downloads JSON/PDF; acknowledges / disputes

Everything shown comes from data/runs/<run_id>/ written by the pipeline. The console writes
only review.json and new rows of the hash-chained event log.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import UploadFile

from turnproof.evidence.canonical import sha256_hex
from turnproof.evidence.pdf import render_packet_pdf
from turnproof.pipeline import ref_time
from turnproof.reason import asr_client
from turnproof.review import jobs
from turnproof.review.state_machine import TransitionError
from turnproof.review.store import RunStore

load_dotenv()  # MODEL_API_KEY for runs started from the console

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
DATA_DIR = Path(os.environ.get("TURNPROOF_DATA", "data"))
ROLES = ("handler", "airline")
DATA_LABEL = "synthetic test data on licensed footage"

app = FastAPI(title="TurnProof console", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
store = RunStore(DATA_DIR)


# ---- helpers ---------------------------------------------------------------------------
def role_of(request: Request) -> str:
    r = request.cookies.get("tp_role", "handler")
    return r if r in ROLES else "handler"


def short(h: str | None, n: int = 12) -> str:
    return (h or "")[:n]


def fmt_t(t: str | None) -> str:
    """2026-10-30T18:01:30.000Z -> 18:01:30Z (date dropped; the page shows it once)."""
    if not t:
        return "unsynced"
    return t[11:19] + "Z" if len(t) >= 19 else t


templates.env.filters["short"] = short
templates.env.filters["fmt_t"] = fmt_t


def ctx(request: Request, **kw) -> dict:
    return {
        "request": request,
        "role": role_of(request),
        "data_label": DATA_LABEL,
        "msg": request.query_params.get("msg"),
        "err": request.query_params.get("err"),
        **kw,
    }


def run_card(run_id: str) -> dict:
    s = store.summary(run_id)
    packet = store.packet(run_id)
    meta = s.get("clip_meta") or {}
    if not meta and packet:
        meta = {
            "flight_number": packet["flight"]["number"],
            "airline": packet["flight"]["airline"],
            "stand": packet["stand"],
            "station": packet["station"],
        }
    if not meta:
        clip = Path(s.get("clip") or s.get("metrics", {}).get("clip", "")).stem
        p = Path("scenarios") / clip / "clip_meta.json"
        meta = json.loads(p.read_text()) if p.exists() else {}
    spark = s.get("spark") or {}
    rcc = spark.get("rule_claim_check") or {}
    return {
        "run_id": run_id,
        "clip": Path(s.get("clip") or s.get("metrics", {}).get("clip", "?")).name,
        "status": s.get("status"),
        "zone": s.get("zone_used"),
        "view": s.get("view"),
        "meta": meta,
        "milestones": s.get("milestones", []),
        "spark_ok": spark.get("ok"),
        "spark_agree": rcc.get("agree"),
        "spark_conf": spark.get("confidence"),
        "review": store.review(run_id),
        "packet_id": packet["packet_id"] if packet else None,
        "proposed": s.get("proposed_claim"),
        "time_sync": s.get("time_sync", {}),
        "cost": (s.get("metrics") or {}).get("est_cost_usd"),
        "created": s.get("created_at_utc"),
        "thumb": thumb_for(run_id, s),
        "duration_s": (s.get("source") or {}).get("duration_s"),
    }


def _img_url(run_id: str, fid: str) -> str | None:
    disp = store.run_dir(run_id) / "display"
    if (disp / f"{fid}_overlay.png").exists():
        return f"/files/{run_id}/display/{fid}_overlay.png"
    if (disp / f"{fid}.png").exists():
        return f"/files/{run_id}/display/{fid}.png"
    return None


def _milestone_frame(s: dict, name: str) -> str | None:
    m = next((m for m in s.get("milestones", []) if m["name"] == name), None)
    return (m or {}).get("evidence_frames", [None])[0]


def hero_frames(run_id: str, s: dict) -> dict:
    """The two pictures that tell the story: equipment at the hold, then the hold clear
    (or, with no candidate, clip start and clip end with the equipment still there)."""
    overlays = sorted(s.get("overlays") or {})
    kf = s.get("keyframe_ids") or []
    lc = _milestone_frame(s, "loading_complete")
    if lc:
        before = kf[0] if kf else _milestone_frame(s, "loader_docked_start")
        after = lc
        titles = ("Equipment at the hold", "Hold clear: loading complete")
    else:
        before = overlays[0] if overlays else "f00000"
        after = overlays[-1] if overlays else None
        titles = ("Clip start", "Clip end: equipment still at the hold")
    fps = (s.get("source") or {}).get("fps") or 24.0

    def one(fid, title):
        if not fid:
            return None
        url = _img_url(run_id, fid)
        if not url:
            return None
        idx = int(fid[1:6]) if fid[1:6].isdigit() else 0
        m = next((m for m in s.get("milestones", []) if fid in m.get("evidence_frames", [])), None)
        ts = s.get("time_sync") or {}
        t_utc = (m or {}).get("t_utc") or ref_time(
            ts.get("reference_start_utc"), idx / fps, ts.get("speed_factor")
        )
        return {"id": fid, "img": url, "title": title, "frame_index": idx, "t_s": idx / fps,
                "t_utc": t_utc, "milestone": (m or {}).get("name")}  # fmt: skip

    return {"before": one(before, titles[0]), "after": one(after, titles[1])}


def thumb_for(run_id: str, s: dict) -> str | None:
    lc = _milestone_frame(s, "loading_complete")
    if lc and _img_url(run_id, lc):
        return _img_url(run_id, lc)
    overlays = sorted(s.get("overlays") or {})
    if overlays:
        return _img_url(run_id, overlays[len(overlays) // 2])
    return _img_url(run_id, "f00000")


def evidence_list(run_id: str, s: dict, packet: dict | None) -> list[dict]:
    frames = s.get("evidence_frames") or (packet or {}).get("evidence_frames") or []
    if not frames:  # very old runs: fall back to the milestone frames
        frames = [
            {"id": fid, "t_utc": m["t_utc"], "frame_index": m["frame_index"]}
            for m in s.get("milestones", [])
            for fid in m.get("evidence_frames", [])
        ]
    disp = store.run_dir(run_id) / "display"
    by_frame = {}
    for m in s.get("milestones", []):
        for fid in m.get("evidence_frames", []):
            by_frame.setdefault(fid, []).append(m["name"])
    kf = set(s.get("keyframe_ids") or [])
    out = []
    for e in frames:
        fid = e["id"]
        has_overlay = (disp / f"{fid}_overlay.png").exists()
        out.append(
            {
                **e,
                "img": f"/files/{run_id}/display/{fid}{'_overlay' if has_overlay else ''}.png",
                "plain": f"/files/{run_id}/display/{fid}.png",
                "roles": by_frame.get(fid, []) + (["spark keyframe"] if fid in kf else []),
            }
        )
    return out


def context_frames(run_id: str, s: dict, evidence: list[dict]) -> list[dict]:
    """Overlay frames that are not milestone evidence (clip start/quarters/end), for the story."""
    ev_ids = {e["id"] for e in evidence}
    out = []
    fps = (s.get("source") or {}).get("fps") or 24.0
    for fid, rel in sorted((s.get("overlays") or {}).items()):
        if fid in ev_ids:
            continue
        idx = int(fid[1:]) if fid[1:].isdigit() else 0
        out.append(
            {"id": fid, "img": f"/files/{run_id}/{rel}", "frame_index": idx, "t_s": idx / fps}
        )
    return out


def run_verifier(packet_path: Path, run_dir: Path, frames_dir: Path | None = None) -> dict:
    cmd = [
        sys.executable,
        str(ROOT / "verify_packet.py"),
        str(packet_path.resolve()),
        "--frames",
        str((frames_dir or run_dir / "display").resolve()),
        "--log",
        str((run_dir / "eventlog.jsonl").resolve()),
    ]
    if os.environ.get("TURNPROOF_PUBLIC_KEY"):
        cmd += ["--pub", os.environ["TURNPROOF_PUBLIC_KEY"]]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=ROOT, timeout=120)
    return {"ok": r.returncode == 0, "exit_code": r.returncode, "output": r.stdout + r.stderr,
            "command": " ".join(c.replace(str(ROOT) + "/", "") for c in cmd[1:])}  # fmt: skip


def _redirect(url: str, msg: str | None = None, err: str | None = None) -> RedirectResponse:
    q = f"?msg={quote(msg)}" if msg else (f"?err={quote(err)}" if err else "")
    return RedirectResponse(url + q, status_code=303)


# ---- pages ------------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    cards = []
    for rid in store.run_ids():
        try:
            cards.append(run_card(rid))
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            continue
    # one card per clip: the newest run, with earlier runs of the same clip listed under it
    groups: dict[str, list[dict]] = {}
    for c in cards:
        groups.setdefault(c["clip"], []).append(c)
    clip_groups = [{"latest": v[0], "earlier": v[1:]} for v in groups.values()]
    # the airline sees only what the handler has sent; ?preview=1 shows the rest for the demo
    visible_states = {"SENT", "ACKNOWLEDGED", "DISPUTED", "RESOLVED"}
    all_packets = [c for c in cards if c["packet_id"]]
    sent = [c for c in all_packets if c["review"]["state"] in visible_states]
    unsent = [c for c in all_packets if c["review"]["state"] not in visible_states]
    preview = request.query_params.get("preview") == "1"
    return templates.TemplateResponse(
        request,
        "index.html",
        ctx(
            request,
            runs=cards,
            processing=processing_runs(),
            scenarios=scenario_options(),
            groups=clip_groups,
            packets=sent + (unsent if preview else []),
            unsent_count=len(unsent),
            preview=preview,
        ),
    )


@app.get("/role/{role}")
def set_role(role: str, next: str = "/"):
    if role not in ROLES:
        raise HTTPException(404)
    resp = RedirectResponse(next if next.startswith("/") else "/", status_code=303)
    resp.set_cookie("tp_role", role, samesite="lax")
    return resp


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_page(request: Request, run_id: str):
    try:
        s = store.summary(run_id)
    except FileNotFoundError as e:
        st = jobs.read_status(store.runs_dir / run_id) if _safe_id(run_id) else None
        if st:
            return templates.TemplateResponse(
                request, "processing.html", ctx(request, run_id=run_id, st=st)
            )
        raise HTTPException(404, "run not found") from e
    packet = store.packet(run_id)
    evidence = evidence_list(run_id, s, packet)
    role = role_of(request)
    return templates.TemplateResponse(
        request,
        "run.html",
        ctx(
            request,
            run_id=run_id,
            s=s,
            card=run_card(run_id),
            packet=packet,
            evidence=evidence,
            context=context_frames(run_id, s, evidence),
            hero=hero_frames(run_id, s),
            occupancy=store.occupancy(run_id),
            review=store.review(run_id),
            actions=store.available_actions(run_id, role),
            events=store.events(run_id),
            metrics=store.metrics(run_id),
            has_video=(store.run_dir(run_id) / "input_h264.mp4").exists(),
        ),
    )


@app.post("/runs/{run_id}/action")
def run_action(request: Request, run_id: str, action: str = Form(...), note: str = Form("")):
    try:
        store.transition(run_id, role_of(request), action, note.strip())
    except TransitionError as e:
        return _redirect(f"/runs/{run_id}", err=str(e))
    except FileNotFoundError as e:
        raise HTTPException(404) from e
    return _redirect(f"/runs/{run_id}", msg=f"{action}: recorded in the event log")


@app.get("/packets/{packet_id}.json")
def packet_json(packet_id: str):
    found = store.find_packet(packet_id)
    if not found:
        raise HTTPException(404)
    run_id, _ = found
    return FileResponse(store.packet_path(run_id), filename=f"{packet_id}.json",
                        media_type="application/json")  # fmt: skip


@app.get("/packets/{packet_id}.pdf")
def packet_pdf(packet_id: str):
    found = store.find_packet(packet_id)
    if not found:
        raise HTTPException(404)
    run_id, packet = found
    run_dir = store.run_dir(run_id)
    out = render_packet_pdf(packet, run_dir, run_dir / "packets" / f"{packet_id}.pdf")
    return FileResponse(out, filename=f"{packet_id}.pdf", media_type="application/pdf")


@app.get("/packets/{packet_id}", response_class=HTMLResponse)
def packet_page(request: Request, packet_id: str):
    found = store.find_packet(packet_id)
    if not found:
        raise HTTPException(404, "packet not found")
    run_id, packet = found
    s = store.summary(run_id)
    role = role_of(request)
    return templates.TemplateResponse(
        request,
        "packet.html",
        ctx(
            request,
            run_id=run_id,
            packet=packet,
            s=s,
            evidence=evidence_list(run_id, s, packet),
            review=store.review(run_id),
            actions=store.available_actions(run_id, role),
            events=store.events(run_id),
        ),
    )


@app.post("/packets/{packet_id}/action")
def packet_action(request: Request, packet_id: str, action: str = Form(...), note: str = Form("")):
    found = store.find_packet(packet_id)
    if not found:
        raise HTTPException(404)
    run_id, _ = found
    try:
        store.transition(run_id, role_of(request), action, note.strip())
    except TransitionError as e:
        return _redirect(f"/packets/{packet_id}", err=str(e))
    return _redirect(f"/packets/{packet_id}", msg=f"{action}: recorded in the event log")


# ---- JSON API (used by the page buttons and by curious judges) ------------------------------
@app.post("/api/packets/{packet_id}/verify")
def api_verify(packet_id: str):
    found = store.find_packet(packet_id)
    if not found:
        raise HTTPException(404)
    run_id, _ = found
    return JSONResponse(run_verifier(store.packet_path(run_id), store.run_dir(run_id)))


@app.post("/api/packets/{packet_id}/tamper")
def api_tamper(packet_id: str):
    """Copy the display frames, change ONE pixel of one evidence frame, verify the copy.
    The original run is untouched. Expected: FAIL on that frame's hash."""
    found = store.find_packet(packet_id)
    if not found:
        raise HTTPException(404)
    run_id, _ = found
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "tamper_demo.py"),
        str(store.packet_path(run_id).resolve()),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=ROOT, timeout=180)
    return JSONResponse(
        {
            "tamper_detected": r.returncode == 0,
            "exit_code": r.returncode,
            "output": r.stdout + r.stderr,
        }
    )


@app.get("/api/runs")
def api_runs():
    return [run_card(r) for r in store.run_ids()]


@app.get("/api/runs/{run_id}")
def api_run(run_id: str):
    try:
        return store.summary(run_id)
    except FileNotFoundError as e:
        raise HTTPException(404) from e


@app.get("/metrics/{run_id}")
def metrics(run_id: str):
    m = store.metrics(run_id)
    if m is None:
        raise HTTPException(404)
    return m


# ---- uploads: the input to TurnProof ---------------------------------------------------------
def _safe_id(v: str) -> bool:
    return bool(v) and "/" not in v and ".." not in v and not v.startswith(".")


def processing_runs() -> list[dict]:
    out = []
    if not store.runs_dir.exists():
        return out
    for d in sorted(store.runs_dir.iterdir(), reverse=True):
        if (d / "run_summary.json").exists():
            continue
        st = jobs.read_status(d)
        if st:
            out.append(st)
    return sorted(out, key=lambda st: st.get("started_at_utc", ""), reverse=True)


def scenario_options() -> list[dict]:
    opts = []
    for meta_path in sorted(Path("scenarios").glob("*/clip_meta.json")):
        meta = json.loads(meta_path.read_text())
        claim_path = meta_path.parent / "airline_claim.json"
        claim = json.loads(claim_path.read_text()) if claim_path.exists() else {}
        opts.append(
            {
                "name": meta_path.parent.name,
                "label": f"{meta_path.parent.name} · {meta.get('flight_number')} {meta.get('airline')} · "
                f"{meta.get('station')} stand {meta.get('stand')} · claim code {claim.get('delay_code')}, "
                f"{claim.get('minutes')} min",
            }
        )
    return opts


def _utc(v: str | None) -> str | None:
    """datetime-local value (entered as UTC) -> ISO Z string; None when blank."""
    v = (v or "").strip()
    if not v:
        return None
    if len(v) == 16:
        v += ":00"
    return v + "Z"


async def _start_upload(
    clip: UploadFile,
    scenario: str,
    reference_start: str | None,
    speed_factor: float,
    speed_source: str,
    view: str,
    use_spark: bool,
    manual: dict | None,
) -> str:
    name = Path(clip.filename or "upload.mp4").name
    stem = (
        "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in Path(name).stem)[:32] or "clip"
    )
    suffix = Path(name).suffix.lower() or ".mp4"
    if suffix not in (".mp4", ".mov", ".m4v", ".mkv", ".avi"):
        raise HTTPException(400, "clip must be a video file (mp4, mov, m4v, mkv, avi)")
    uploads = DATA_DIR / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    run_id = f"{stem}-{os.urandom(4).hex()}"
    dest = uploads / f"{run_id}{suffix}"
    with dest.open("wb") as fh:
        while chunk := await clip.read(1 << 20):
            fh.write(chunk)
    if manual:
        scen_dir = jobs.write_scenario(
            DATA_DIR / "scenarios" / run_id, manual["meta"], manual["claim"], manual["log"]
        )
    else:
        scen_dir = Path("scenarios") / scenario
        if not _safe_id(scenario) or not (scen_dir / "clip_meta.json").exists():
            raise HTTPException(400, "unknown scenario")
    if view not in jobs.VIEWS:
        raise HTTPException(400, "unknown camera view")
    clip_cfg = {
        "reference_start_utc": _utc(reference_start),
        "speed_factor": float(speed_factor) if speed_factor else None,
        "speed_factor_source": speed_source,
        "view": view,
    }
    return jobs.start_run(
        dest, clip_cfg=clip_cfg, scenario_dir=scen_dir, data_dir=DATA_DIR,
        use_spark=use_spark, run_id=run_id,
    )  # fmt: skip


def _manual_from_form(f) -> dict | None:
    """Claim and log typed into the form; None when the flight number is blank."""
    flight = (f.get("m_flight") or "").strip()
    if not flight:
        return None
    meta = {
        "station": (f.get("m_station") or "").strip() or "XXX",
        "stand": (f.get("m_stand") or "").strip() or "?",
        "flight_number": flight,
        "flight_date": (f.get("m_date") or "").strip() or "2026-01-01",
        "airline": (f.get("m_airline") or "").strip() or "Airline",
        "handler": (f.get("m_handler") or "").strip() or "Handler",
        "camera_id": (f.get("m_camera") or "").strip() or "stand-cam",
        "data_label": "synthetic test data",
    }
    start, end = _utc(f.get("m_win_start")), _utc(f.get("m_win_end"))
    claim = {
        "delay_code": (f.get("m_code") or "32").strip(),
        "minutes": int(f.get("m_minutes") or 0),
        "source": "synthetic test data (console entry)",
    }
    if start and end:
        claim["claim_window_utc"] = {"start": start, "end": end}
    log = [
        {"milestone": m, "t_utc": _utc(f.get(k))}
        for m, k in (
            ("loader_docked_start", "m_log_docked"),
            ("loading_complete", "m_log_complete"),
            ("hold_door_closed", "m_log_door"),
        )
        if _utc(f.get(k))
    ]
    return {"meta": meta, "claim": claim, "log": log}


@app.get("/upload", response_class=HTMLResponse)
def upload_form(request: Request):
    return templates.TemplateResponse(
        request, "upload.html", ctx(request, scenarios=scenario_options(), views=jobs.VIEWS)
    )


@app.post("/upload")
async def upload(request: Request):
    form = await request.form()
    clip = form.get("clip")
    if not isinstance(clip, UploadFile) or not clip.filename:
        return _redirect("/upload", err="choose a video file first")
    try:
        run_id = await _start_upload(
            clip,
            str(form.get("scenario") or ""),
            str(form.get("reference_start") or ""),
            float(form.get("speed_factor") or 1.0),
            str(form.get("speed_source") or "declared_by_uploader"),
            str(form.get("view") or "front_quarter"),
            form.get("use_spark") is not None,
            _manual_from_form(form),
        )
    except HTTPException as e:
        return _redirect("/upload", err=str(e.detail))
    return _redirect(f"/runs/{run_id}", msg="upload received; the run has started")


@app.post("/api/upload")
async def api_upload(request: Request):
    """Machine entry point (a station's video system can push clips): multipart, same fields
    as the form. Returns the run id and where to poll."""
    form = await request.form()
    clip = form.get("clip")
    if not isinstance(clip, UploadFile) or not clip.filename:
        raise HTTPException(400, "multipart field 'clip' (video file) is required")
    run_id = await _start_upload(
        clip,
        str(form.get("scenario") or "clip1"),
        str(form.get("reference_start") or ""),
        float(form.get("speed_factor") or 1.0),
        str(form.get("speed_source") or "declared_by_uploader"),
        str(form.get("view") or "front_quarter"),
        str(form.get("use_spark") or "1") not in ("0", "false", "no"),
        None,
    )
    return {"run_id": run_id, "status": f"/api/runs/{run_id}/status", "page": f"/runs/{run_id}"}


@app.get("/api/runs/{run_id}/status")
def api_status(run_id: str):
    if not _safe_id(run_id):
        raise HTTPException(404)
    st = jobs.read_status(store.runs_dir / run_id)
    if not st:
        raise HTTPException(404)
    return st


# ---- operator statement: typed, or spoken and transcribed by Muse Voice Transcribe ---------
@app.post("/runs/{run_id}/statement")
async def statement(request: Request, run_id: str):
    form = await request.form()
    audio = form.get("audio")
    text = str(form.get("text") or "").strip()
    try:
        store.run_dir(run_id)
    except FileNotFoundError as e:
        raise HTTPException(404) from e
    if isinstance(audio, UploadFile) and audio.filename:
        raw = await audio.read()
        try:
            suffix = Path(audio.filename).suffix or ".webm"
            wav = raw if suffix == ".wav" else asr_client.to_wav(raw, suffix)
            res = asr_client.transcribe(wav)
        except Exception as e:  # noqa: BLE001 - show the operator what failed
            return _redirect(f"/runs/{run_id}", err=f"transcription failed: {e}")
        if not res["text"]:
            return _redirect(f"/runs/{run_id}", err="transcription returned no text; try again")
        stmt = {
            "text": res["text"],
            "source": "spoken",
            "model": res["model"],
            "audio_sha256": sha256_hex(wav),
            "recorded_at_utc": jobs._now(),
            "operator": "handler_operator",
        }
    elif text:
        stmt = {
            "text": text,
            "source": "typed",
            "model": None,
            "audio_sha256": None,
            "recorded_at_utc": jobs._now(),
            "operator": "handler_operator",
        }
    else:
        return _redirect(f"/runs/{run_id}", err="record a statement or type one")
    store.set_statement(run_id, stmt)
    return _redirect(f"/runs/{run_id}", msg="statement recorded in the event log")


# ---- files -----------------------------------------------------------------------------------
@app.get("/files/{run_id}/display/{name}")
def display_file(run_id: str, name: str):
    if "/" in name or ".." in name or not name.endswith(".png"):
        raise HTTPException(404)
    try:
        p = store.run_dir(run_id) / "display" / name
    except FileNotFoundError as e:
        raise HTTPException(404) from e
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/png")


@app.get("/files/{run_id}/video")
def video_file(run_id: str):
    try:
        p = store.run_dir(run_id) / "input_h264.mp4"
    except FileNotFoundError as e:
        raise HTTPException(404) from e
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="video/mp4")
