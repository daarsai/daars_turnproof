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

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from turnproof.evidence.pdf import render_packet_pdf
from turnproof.pipeline import ref_time
from turnproof.review.state_machine import TransitionError
from turnproof.review.store import RunStore

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
    packets = [c for c in cards if c["packet_id"]]
    return templates.TemplateResponse(
        request, "index.html", ctx(request, runs=cards, packets=packets)
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
