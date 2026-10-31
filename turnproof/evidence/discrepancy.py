"""Discrepancy table: video milestones vs handler log vs airline claim, in minutes."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s).astimezone(UTC) if s else None


def load_claim(path: Path) -> dict:
    return json.loads(path.read_text())


def load_handler_log(path: Path) -> list[dict]:
    with path.open() as fh:
        return [{"milestone": r["milestone"], "t_utc": r["t_utc"]} for r in csv.DictReader(fh)]


def video_supported_minutes(claim: dict, loading_complete_utc: str | None) -> int | None:
    """Minutes of the airline's claim window during which loading was STILL IN PROGRESS
    (i.e. before loading_complete). Those are the only minutes video can attribute to loading.
    None if the window is unknown or the clip is unsynced."""
    w = claim.get("claim_window_utc")
    lc = _dt(loading_complete_utc)
    if not w or lc is None:
        return None
    start, end = _dt(w["start"]), _dt(w["end"])
    if start is None or end is None:
        return None
    overlap_end = min(end, lc)
    return max(0, round((overlap_end - start).total_seconds() / 60))


def build(milestones: list[dict], handler_log: list[dict], claim: dict) -> list[dict]:
    log_by = {e["milestone"]: e["t_utc"] for e in handler_log}
    claimed = int(claim.get("minutes", 0))
    lc = next((m for m in milestones if m["name"] == "loading_complete"), None)
    supported = video_supported_minutes(claim, lc["t_utc"] if lc else None)
    rows = []
    for m in milestones:
        v, h = m.get("t_utc"), log_by.get(m["name"])
        delta_log = round((_dt(v) - _dt(h)).total_seconds() / 60, 1) if v and h else None
        rows.append(
            {
                "milestone": m["name"],
                "video_utc": v,
                "handler_log_utc": h,
                "video_minus_log_min": delta_log,
                "airline_claim_minutes": claimed,
                "video_supported_minutes": supported if m["name"] == "loading_complete" else None,
                "delta_min": (claimed - supported)
                if (m["name"] == "loading_complete" and supported is not None)
                else None,
            }
        )
    return rows


def proposed_claim(claim: dict, rows: list[dict], family: str) -> dict:
    lc = next((r for r in rows if r["milestone"] == "loading_complete"), None)
    supported = lc["video_supported_minutes"] if lc else None
    if supported is None:
        basis = "cannot be computed: clip unsynced or claim window missing"
    elif supported == 0:
        basis = "loading_complete observed before the claimed delay window"
    else:
        basis = f"{supported} min of the claimed window fall after loading_complete"
    return {
        "delay_code_family": family or "none",
        "minutes_supported_by_video": supported if supported is not None else -1,
        "basis": basis,
    }
