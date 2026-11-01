"""Upload from the console starts a background run (fake model clients, tiny synthetic clip)."""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from turnproof import pipeline as pl
from turnproof.reason import asr_client
from turnproof.review import app as app_mod
from turnproof.review.store import RunStore

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

N, LEAVE, FPS, W, H = 480, 300, 24, 640, 258
AC = "<|box;x1=196;y1=0;x2=633;y2=181;w=640;h=258;c=0.95|>"
VE = "<|box;x1=320;y1=108;x2=415;y2=165;w=640;h=258;c=0.9|>"


class FakeSam:
    def __init__(self, *a, **k):
        self.calls = []

    def segment_video(self, path, concept):
        self.calls.append({"concept": concept, "cached": True})
        lines = []
        for i in range(N):
            if concept == "aircraft":
                lines.append(f"<{i}f>0{AC}")
            elif concept == "vehicle" and i < LEAVE:
                lines.append(f"<{i}f>0{VE}")
            else:
                lines.append(f"<{i}f>")
        return "\n".join(lines)


class FakeSpark:
    prompt_version = "test"
    prompt_sha256 = "0" * 64

    def __init__(self, *a, **k):
        self.calls = []

    def evaluate(self, paths, ids, ctx):
        return {"ok": True, "path": "json_schema", "out": {
            "observed_facts": [{"text": "gone", "frames": [ids[1]]}], "hold_door_state": "unknown",
            "rule_claim_check": {"claim": "loader_departed", "agree": True, "reason": "empty"},
            "candidate_delay_code_family": "none", "confidence": 0.8, "requires_operator_review": False,
        }}  # fmt: skip


def _clip(path: Path) -> None:
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for i in range(N):
        img = np.full((H, W, 3), 120, np.uint8)
        cv2.rectangle(img, (196, 0), (633, 181), (200, 200, 200), -1)
        if i < LEAVE:
            cv2.rectangle(img, (320, 108), (415, 165), (0, 120, 0), -1)
        vw.write(img)
    vw.release()


def test_upload_starts_a_run_and_the_console_follows_it(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # pipeline writes data/ and reads config/, scenarios/ from cwd
    root = Path(__file__).parent.parent
    shutil.copytree(root / "config", tmp_path / "config")
    shutil.copytree(root / "scenarios", tmp_path / "scenarios")
    (tmp_path / "keys").mkdir()
    subprocess.run(
        [sys.executable, str(root / "scripts" / "gen_keys.py")], check=True, capture_output=True
    )
    monkeypatch.setenv("TURNPROOF_PUBLIC_KEY", str(tmp_path / "keys" / "turnproof-demo-2026.pub"))
    monkeypatch.setattr(pl, "SamClient", FakeSam)
    monkeypatch.setattr(pl, "SparkClient", FakeSpark)
    monkeypatch.setattr(app_mod, "DATA_DIR", Path("data"))
    monkeypatch.setattr(app_mod, "store", RunStore(Path("data")))
    _clip(tmp_path / "test_clip.mp4")

    c = TestClient(app_mod.app)
    r = c.get("/upload")
    assert r.status_code == 200 and 'name="clip"' in r.text
    with (tmp_path / "test_clip.mp4").open("rb") as fh:
        r = c.post(
            "/api/upload",
            files={"clip": ("test_clip.mp4", fh, "video/mp4")},
            data={
                "scenario": "clip1",
                "reference_start": "2026-10-30T17:58",
                "speed_factor": "6",
                "speed_source": "declared_by_uploader",
                "view": "side",
            },
        )
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]
    assert run_id.startswith("test_clip-")

    # processing page while it runs, then the real run page
    deadline = time.time() + 120
    while time.time() < deadline:
        st = c.get(f"/api/runs/{run_id}/status").json()
        if st["state"] in ("done", "failed"):
            break
        time.sleep(0.5)
    assert st["state"] == "done", st
    r = c.get(f"/runs/{run_id}")
    assert r.status_code == 200 and "loading_complete" in r.text
    s = json.loads((tmp_path / "data" / "runs" / run_id / "run_summary.json").read_text())
    assert s["status"] == "candidate" and s["time_sync"]["speed_factor"] == 6.0
    assert s["view"] == "side"
    assert (tmp_path / "data" / "runs" / run_id / "occupancy.json").exists()
    assert c.get("/").status_code == 200

    # a typed statement, then confirm + send -> statement is inside the re-issued, signed packet
    r = c.post(
        f"/runs/{run_id}/statement",
        data={"text": "Loader left before the window."},
        follow_redirects=False,
    )
    assert r.status_code == 303 and "msg=" in r.headers["location"]
    c.post(f"/runs/{run_id}/action", data={"action": "confirm", "note": "ok"})
    c.post(f"/runs/{run_id}/action", data={"action": "send"})
    p = app_mod.store.packet(run_id)
    assert p["human_statement"]["text"] == "Loader left before the window."
    assert p["review"]["decision"] == "confirmed"
    v = c.post(f"/api/packets/{p['packet_id']}/verify").json()
    assert v["ok"], v["output"]


def test_asr_response_parsing():
    f = asr_client._extract_text
    assert f({"text": "hello"}) == "hello"
    assert f({"results": [{"transcript": "a"}, {"transcript": "b"}]}) == "a b"
    assert f({"output": {"transcription": "x"}}) == "x"
    assert f({"nothing": 1}) == ""
