"""Claim-vs-video outcome wording, the empty console (no pre-defined claims) and reset-demo."""

import json
import shutil
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from turnproof.review import app as app_mod
from turnproof.review import views
from turnproof.review.store import RunStore

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import reset_demo

META = {"sla_penalty_per_min": 40, "currency": "EUR"}


def _fig(claimed, supported, why=None, no_claim=False):
    return {"claimed": claimed, "supported": supported, "supported_why": why,
            "no_claim": no_claim, "basis": "basis", "code": "32"}  # fmt: skip


def test_outcome_not_supported_means_no_penalty_minutes():
    o = views.outcome(_fig(9, 0), META)
    assert o["kind"] == "not_supported" and o["tone"] == "good"
    assert o["money"] == {"claimed": 360.0, "supported": 0.0, "not_supported": 360.0,
                          "rate": 40.0, "currency": "EUR"}  # fmt: skip
    assert "No penalty minutes" in o["text"] and "EUR 360 not supported" in o["text"]


def test_outcome_partly_and_fully_supported():
    o = views.outcome(_fig(12, 4), META)
    assert o["kind"] == "partly_supported" and o["short"] == "4 of 12 min"
    assert o["money"]["supported"] == 160.0 and o["money"]["not_supported"] == 320.0
    o = views.outcome(_fig(6, 6), META)
    assert o["kind"] == "supported" and o["money"]["not_supported"] == 0.0
    # more minutes than claimed never happens from the rule, but is still "supported"
    assert views.outcome(_fig(3, 4), META)["kind"] == "supported"


def test_outcome_undetermined_and_no_claim_have_no_money():
    o = views.outcome(_fig(9, None, "Time not synchronized"), META)
    assert o["kind"] == "undetermined" and o["money"] is None
    assert "time not synchronized" in o["label"]
    o = views.outcome(_fig(None, None, None, no_claim=True), META)
    assert o["kind"] == "no_claim" and o["money"] is None
    # no contract rate on file: wording without money
    o = views.outcome(_fig(9, 0), {})
    assert o["kind"] == "not_supported" and o["money"] is None and "EUR" not in o["text"]


def test_console_starts_without_predefined_claims(tmp_path, monkeypatch):
    """The repo's scenarios/ are test fixtures; the console lists only claims registered in it."""
    monkeypatch.chdir(tmp_path)
    shutil.copytree(ROOT / "config", tmp_path / "config")
    shutil.copytree(ROOT / "scenarios", tmp_path / "scenarios")
    monkeypatch.setattr(app_mod, "DATA_DIR", Path("data"))
    monkeypatch.setattr(app_mod, "store", RunStore(Path("data")))
    assert app_mod.claim_records() == [] and app_mod.scenario_options() == []
    assert app_mod.scenario_for_flight("XY123", "2026-10-30") is None
    # explicit names still resolve for scripts calling POST /api/upload
    assert app_mod.scenario_dir("clip1") == Path("scenarios/clip1")
    c = TestClient(app_mod.app)
    r = c.get("/upload")
    assert r.status_code == 200 and "No claim on file" in r.text and "clip1" not in r.text
    assert c.get("/claims").status_code == 200 and c.get("/").status_code == 200
    # a claim registered in the console is offered
    d = tmp_path / "data" / "scenarios" / "xy123-demo"
    d.mkdir(parents=True)
    (d / "clip_meta.json").write_text(json.dumps({"flight_number": "XY123", "airline": "XY Airways",
        "flight_date": "2026-10-30", "station": "BLR", "stand": "D14"}))  # fmt: skip
    (d / "airline_claim.json").write_text(json.dumps({"delay_code": "32", "minutes": 9}))
    assert [o["name"] for o in app_mod.scenario_options()] == ["xy123-demo"]
    assert app_mod.scenario_for_flight("XY123", "2026-10-30") == Path("data/scenarios/xy123-demo")
    assert "xy123-demo" in c.get("/upload").text


def test_reset_demo_archives_without_deleting(tmp_path):
    data = tmp_path / "data"
    for name in ("runs/r1", "scenarios/s1", "uploads", "webhook_inbox", "cache", "archive"):
        (data / name).mkdir(parents=True)
    (data / "runs/r1/run_summary.json").write_text("{}")
    (data / "cache/sam.json").write_text("{}")
    (data / "cameras.json").write_text("[]")
    dest = reset_demo.reset(data)
    assert dest and dest.parent == data / "archive"
    assert (dest / "runs/r1/run_summary.json").exists() and (dest / "scenarios/s1").is_dir()
    assert not (data / "runs").exists() and not (data / "scenarios").exists()
    assert (data / "cache/sam.json").exists() and (data / "cameras.json").exists()
    assert reset_demo.reset(data) is None  # nothing left to move
