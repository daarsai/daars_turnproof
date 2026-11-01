"""Station: flight feed x stand cameras -> a capture from the 'camera' (a local file here) runs
the pipeline with the feed's on-block time as the declared start."""

import json
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_upload import FakeSam, FakeSpark, _clip
from turnproof import pipeline as pl
from turnproof.ingest import flights as flights_mod
from turnproof.ingest.camera import load_cameras, probe, record, redact_url
from turnproof.review import app as app_mod
from turnproof.review.store import RunStore

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
ROOT = Path(__file__).parent.parent


def test_plan_pairs_flights_with_cameras():
    fl = flights_mod.load_aodb_file(ROOT / "config" / "flights_demo.json")
    cams = load_cameras(ROOT / "config" / "cameras_demo.json")
    now = datetime(2026, 10, 30, 18, 0, tzinfo=UTC)
    w = {x.flight.flight_number: x for x in flights_mod.plan(fl, cams, now)}
    assert w["XY123"].state == "due" and w["XY123"].camera.id == "stand-d14-01"
    assert w["XY456"].state == "planned"
    assert "XY789" not in w  # stand C02 has no camera
    assert [f.flight_number for f in flights_mod.flights_without_camera(fl, cams)] == ["XY789"]
    assert redact_url("rtsp://user:secret@10.0.0.5/x") == "rtsp://10.0.0.5/x"


def test_record_and_probe_local_file(tmp_path):
    src = tmp_path / "cam.mp4"
    _clip(src)
    assert probe(str(src))["ok"]
    out = record(str(src), 3, tmp_path / "cap.mp4")
    assert out.stat().st_size > 1024 and probe(str(out))["ok"]
    assert probe("rtsp://127.0.0.1:1/nothing", timeout_s=5)["ok"] is False


def test_station_capture_runs_the_pipeline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    shutil.copytree(ROOT / "config", tmp_path / "config")
    shutil.copytree(ROOT / "scenarios", tmp_path / "scenarios")
    (tmp_path / "keys").mkdir()
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/gen_keys.py")], check=True, capture_output=True
    )
    monkeypatch.setenv("TURNPROOF_PUBLIC_KEY", str(tmp_path / "keys/turnproof-demo-2026.pub"))
    monkeypatch.setattr(pl, "SamClient", FakeSam)
    monkeypatch.setattr(pl, "SparkClient", FakeSpark)
    monkeypatch.setattr(app_mod, "DATA_DIR", Path("data"))
    monkeypatch.setattr(app_mod, "store", RunStore(Path("data")))
    # the "camera" is a local file for the test
    src = tmp_path / "stand.mp4"
    _clip(src)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "cameras.json").write_text(
        json.dumps([{"id": "cam-d14", "stand": "D14", "station": "BLR", "url": str(src),
                     "view": "side", "speed_factor": 6.0,
                     "speed_factor_source": "estimated_from_vehicle_motion", "note": ""}])
    )  # fmt: skip

    c = TestClient(app_mod.app)
    r = c.get("/station")
    assert r.status_code == 200 and "XY123" in r.text and "cam-d14" in r.text
    plan = c.get("/api/station/plan").json()
    assert plan[0]["flight"]["flight_number"] == "XY123" and plan[0]["camera"]["id"] == "cam-d14"

    r = c.post(
        "/station/capture",
        data={"flight_number": "XY123", "flight_date": "2026-10-30", "camera_id": "cam-d14",
              "seconds": "8", "event": "loading"},
        follow_redirects=False,
    )  # fmt: skip
    assert r.status_code == 303, r.text
    run_id = r.headers["location"].split("/runs/")[1].split("?")[0]
    assert run_id.startswith("xy123-d14-")
    deadline = time.time() + 120
    while time.time() < deadline:
        st = c.get(f"/api/runs/{run_id}/status").json()
        if st["state"] in ("done", "failed"):
            break
        time.sleep(0.5)
    assert st["state"] == "done", st
    assert st["capture"]["flight_number"] == "XY123"
    s = json.loads((tmp_path / "data/runs" / run_id / "run_summary.json").read_text())
    assert s["time_sync"]["reference_start_utc"] == "2026-10-30T17:58:00Z"  # from the feed
    assert s["time_sync"]["speed_factor"] == 6.0 and s["view"] == "side"
    assert s["clip_meta"]["flight_number"] == "XY123"  # claim attached by flight number
    assert c.get(f"/runs/{run_id}").status_code == 200


def test_adsb_adapter_maps_opensky_rows(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"icao24": "abc123", "callsign": "XYZ123 ", "lastSeen": 1793500000}]

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None):
            assert params["airport"] == "VOBL"
            return FakeResp()

    monkeypatch.setattr(flights_mod.httpx, "Client", FakeClient)
    fl = flights_mod.opensky_arrivals("VOBL", 2, "BLR")
    assert fl[0].flight_number == "XYZ123" and fl[0].source == "adsb_opensky"
    assert fl[0].stand is None and fl[0].landed_utc.endswith("Z")
