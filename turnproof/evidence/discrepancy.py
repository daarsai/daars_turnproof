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


def build(
    milestones: list[dict],
    handler_log: list[dict],
    claim: dict,
    end_name: str = "loading_complete",
) -> list[dict]:
    """end_name: the milestone that ends the event (loading_complete, fuelling_complete...)."""
    log_by = {e["milestone"]: e["t_utc"] for e in handler_log}
    claimed = int(claim.get("minutes", 0))
    lc = next((m for m in milestones if m["name"] == end_name), None)
    supported = video_supported_minutes(claim, lc["t_utc"] if lc else None)
    rows = []
    for m in milestones:
        v, h = m.get("t_utc"), log_by.get(m["name"])
        at_start = m.get("method", "").endswith("present_at_clip_start")
        delta_log = round((_dt(v) - _dt(h)).total_seconds() / 60, 1) if v and h else None
        note = None
        if at_start:
            # The video only proves presence BY this time; an earlier log time is consistent.
            consistent = (h is None) or (v is None) or (_dt(h) <= _dt(v))
            delta_log = None
            note = "equipment already present at clip start; video gives an upper bound only" + (
                "; log time is consistent" if consistent else "; log time is LATER than video"
            )
        elif v is None:
            note = "clip unsynced: no real-world time"
        rows.append(
            {
                "milestone": m["name"],
                "video_utc": v,
                "handler_log_utc": h,
                "video_minus_log_min": delta_log,
                "note": note,
                "airline_claim_minutes": claimed,
                "video_supported_minutes": supported if m["name"] == end_name else None,
                "delta_min": (claimed - supported)
                if (m["name"] == end_name and supported is not None)
                else None,
            }
        )
    return rows


LOADING_FAMILIES = {"31", "32", "33", "34", "35", "36", "37", "38", "39"}


def proposed_claim(
    claim: dict,
    rows: list[dict],
    *,
    has_loading_complete: bool,
    synced: bool,
    spark_agrees: bool | None,
    end_name: str = "loading_complete",
    families: set[str] | None = None,
) -> dict:
    """What the video can back, from the RULE alone. The delay-code family is the airline's own
    claimed code, and only when the video supports more than zero minutes of its window; it is
    never taken from a model answer. Spark's suggested family stays in models.spark as a note."""
    lc = next((r for r in rows if r["milestone"] == end_name), None)
    supported = lc["video_supported_minutes"] if lc else None
    claimed = str(claim.get("delay_code", "")).strip()
    fams = families if families is not None else LOADING_FAMILIES
    family = claimed[:2] if claimed[:2] in fams else "none"
    if not has_loading_complete:
        family, supported, basis = (
            "none",
            None,
            f"no {end_name} observed: equipment still in the zone when the clip ends",
        )
    elif spark_agrees is False:
        family, supported, basis = (
            "none",
            None,  # no minutes stated until a human decides
            "keyframe review disagrees with the detected departure; operator decision required",
        )
    elif not synced:
        family, supported = "none", None
        basis = "clip unsynced: no real-world minutes can be computed"
    elif supported is None:
        family, basis = "none", "claim window missing: minutes cannot be computed"
    elif supported == 0:
        family, basis = "none", f"{end_name} observed before the claimed delay window"
    elif family == "none":
        basis = (
            f"{supported} min of the claimed window overlap the event in progress, but claimed "
            f"code {claimed} is not in this event's delay-code families ({', '.join(sorted(fams))})"
        )
    else:
        basis = f"{supported} min of the claimed window overlap the event in progress"
    return {
        "delay_code_family": family,
        "minutes_supported_by_video": supported,  # None = cannot be computed
        "basis": basis,
    }
