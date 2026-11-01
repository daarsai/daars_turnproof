"""Claim intake: telex parser, extraction route with a stubbed Spark, confirm -> scenario."""

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from turnproof.reason import intake
from turnproof.review import app as app_mod
from turnproof.review.store import RunStore

MVT = "MVT\nXY123/30.VTABC.BLR\nAD1814/1826 EA1935 DEL\nDL32/0009\nSI LATE LOADING AT STAND D14"


def test_local_telex_parser():
    assert intake.parse_mvt_locally("DL32/0009") == {
        "delay_code": "32",
        "minutes": 9,
        "source_quote": "DL32/0009",
    }
    assert intake.parse_mvt_locally("DLA/36A/0112 fuel")["minutes"] == 72
    assert intake.parse_mvt_locally("no codes here") is None


def test_intake_extract_and_confirm(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scenarios").mkdir()
    shutil.copytree(Path(__file__).parent.parent / "config", tmp_path / "config")
    monkeypatch.setattr(app_mod, "DATA_DIR", Path("data"))
    monkeypatch.setattr(app_mod, "store", RunStore(Path("data")))

    def fake_extract(text, img=None, mime="image/jpeg", **kw):
        return {
            "ok": True,
            "claim": {
                "delay_code": "32",
                "minutes": 9,
                "flight_number": "XY123",
                "flight_date": "2026-10-30",
                "airline": "XY Airways",
                "station": "BLR",
                "claim_window_start_utc": "2026-10-30T18:05:00Z",
                "claim_window_end_utc": "2026-10-30T18:14:00Z",
                "message_type": "MVT",
                "source_quote": "DL32/0009",
                "confidence": 0.93,
                "notes": "",
            },
            "raw": "{}",
            "tokens_in": 10,
            "tokens_out": 5,
            "seconds": 0.1,
            "input_sha256": "x",
            "prompt_version": intake.INTAKE_PROMPT_VERSION,
            "model": "muse-spark-1.3",
            "error": None,
        }

    monkeypatch.setattr(intake, "extract_claim", fake_extract)
    c = TestClient(app_mod.app)
    assert c.get("/intake").status_code == 200
    r = c.post("/intake/extract", data={"message": MVT})
    assert r.status_code == 200
    assert "extracted · MVT" in r.text and "agrees" in r.text  # Spark and the telex parser match
    r = c.post(
        "/intake/confirm",
        data={
            "message": MVT,
            "message_type": "MVT",
            "delay_code": "32",
            "minutes": "9",
            "window_start": "2026-10-30T18:05:00",
            "window_end": "2026-10-30T18:14:00",
            "flight_number": "XY123",
            "flight_date": "2026-10-30",
            "airline": "XY Airways",
            "station": "BLR",
            "stand": "D14",
            "handler": "Handler Co",
            "sla_rate": "40",
            "currency": "EUR",
            "spark_model": "muse-spark-1.3",
            "spark_prompt_version": "p",
            "spark_raw": "{}",
            "spark_confidence": "0.93",
            "log_complete": "2026-10-30T18:04",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    name = r.headers["location"].split("scenario=")[1].split("&")[0]
    d = Path("data/scenarios") / name
    claim = json.loads((d / "airline_claim.json").read_text())
    assert claim["delay_code"] == "32" and claim["minutes"] == 9
    assert claim["claim_window_utc"]["start"] == "2026-10-30T18:05:00Z"
    assert "Muse Spark claim intake" in claim["source"]
    meta = json.loads((d / "clip_meta.json").read_text())
    assert meta["sla_penalty_per_min"] == 40.0 and meta["flight_number"] == "XY123"
    assert (d / "handler_log.csv").read_text().strip().splitlines()[1] == (
        "loading_complete,2026-10-30T18:04:00Z"
    )
    assert json.loads((d / "intake.json").read_text())["spark"]["confidence"] == "0.93"
    # the new scenario is offered in the upload form, preselected
    r = c.get(f"/upload?scenario={name}")
    assert f'value="{name}" selected' in r.text and "from claim intake" in r.text
    assert app_mod.scenario_dir(name) == d
