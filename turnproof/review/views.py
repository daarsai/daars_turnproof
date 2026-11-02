"""Presentation helpers for the console: labels, case grouping, comparison timelines.

Read-only views over what the pipeline and the review store already wrote. Nothing here
changes a record, a state or a number; when a value cannot be derived it is reported as
unavailable instead of being filled in.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from turnproof.pipeline import ref_time

SENT_STATES = ("SENT", "ACKNOWLEDGED", "DISPUTED", "RESOLVED")

REVIEW_LABELS = {
    "OBSERVED": ("No decision needed", "neutral"),
    "CANDIDATE": ("Awaiting AI keyframe check", "warn"),
    "UNDER_REVIEW": ("Awaiting human review", "warn"),
    "CONFIRMED": ("Confirmed · ready to send", "good"),
    "REJECTED": ("Rejected by handler", "bad"),
    "SENT": ("Sent to airline", "info"),
    "ACKNOWLEDGED": ("Acknowledged by airline", "good"),
    "DISPUTED": ("Disputed by airline", "bad"),
    "RESOLVED": ("Resolved", "good"),
    "ARCHIVED": ("Archived", "neutral"),
}

MILESTONE_LABELS = {
    "loader_docked_start": "Loading equipment at the hold",
    "loading_complete": "Loading complete",
    "hold_door_closed": "Hold door closed",
}


NEXT_STEPS = {
    "DISPUTED": ("Resolve the dispute", 0),
    "UNDER_REVIEW": ("Review the evidence", 1),
    "CONFIRMED": ("Send the packet", 2),
    "CANDIDATE": ("Waiting for the AI keyframe check", 3),
    "SENT": ("Waiting for the airline", 4),
    "OBSERVED": ("No decision needed", 5),
    "ACKNOWLEDGED": ("Closed · acknowledged", 6),
    "RESOLVED": ("Closed · resolved", 6),
    "REJECTED": ("Closed · rejected", 7),
    "ARCHIVED": ("Archived", 8),
}


def next_step(state: str | None) -> dict:
    label, rank = NEXT_STEPS.get(state or "", ("—", 9))
    return {"label": label, "rank": rank, "open": rank <= 4}


def parse_t(t: str | None) -> datetime | None:
    if not t:
        return None
    try:
        return datetime.fromisoformat(t)
    except ValueError:
        return None


def hm(t: str | None) -> str:
    """'2026-10-30T18:01:30.210Z' -> '18:01:30'; '...18:05:00Z' -> '18:05'; None -> '—'."""
    d = parse_t(t)
    if d is None:
        return "—"
    return d.strftime("%H:%M") if d.second == 0 else d.strftime("%H:%M:%S")


def day(t: str | None) -> str:
    d = parse_t(t)
    return d.strftime("%d %b %Y") if d else ""


def milestone_label(name: str | None) -> str:
    if not name:
        return ""
    if name in MILESTONE_LABELS:
        return MILESTONE_LABELS[name]
    return name.replace("_", " ").capitalize()


def review_label(state: str | None) -> dict:
    label, tone = REVIEW_LABELS.get(state or "", (state or "Unknown", "neutral"))
    return {"label": label, "tone": tone, "state": state}


def is_placeholder_claim(claim: dict | None) -> bool:
    if not claim:
        return True
    return "placeholder" in str(claim.get("source", "")) or (
        str(claim.get("delay_code")) == "00" and not claim.get("minutes")
    )


def evidence_status(s: dict) -> dict:
    """What the analysis run found, in the backend's own terms (status + time sync + Spark)."""
    status = s.get("status")
    synced = (s.get("time_sync") or {}).get("status") == "declared"
    spark = s.get("spark") or {}
    agree = (spark.get("rule_claim_check") or {}).get("agree")
    if status == "candidate":
        if spark.get("ok") and agree is False:
            return {"label": "AI review required", "tone": "warn",
                    "detail": "Muse Spark disagrees with the detected event"}  # fmt: skip
        return {"label": "Candidate event detected", "tone": "good",
                "detail": "Event detected on synchronized footage"}  # fmt: skip
    if status == "candidate_unsynced":
        return {"label": "Time not synchronized", "tone": "warn",
                "detail": "Event detected, but the clip has no declared start time"}  # fmt: skip
    if status == "no_candidate":
        return {"label": "No complete event detected", "tone": "neutral",
                "detail": readable((s.get("proposed_claim") or {}).get("basis"))
                + ("" if synced else " · time not synchronized")}  # fmt: skip
    return {"label": "Not processed", "tone": "neutral", "detail": ""}


def figures(s: dict, claim: dict | None) -> dict:
    """Claimed / video-supported / difference, or why a figure cannot be determined."""
    pc = s.get("proposed_claim") or {}
    sup = pc.get("minutes_supported_by_video")
    no_claim = is_placeholder_claim(claim)
    claimed = None if no_claim else int((claim or {}).get("minutes") or 0)
    if sup is None:
        if (s.get("time_sync") or {}).get("status") != "declared":
            why = "Time not synchronized"
        elif s.get("status") == "no_candidate":
            why = "Insufficient evidence"
        else:
            why = "Not determined"
    else:
        why = None
    diff = claimed - int(sup) if (claimed is not None and sup is not None) else None
    win = (claim or {}).get("claim_window_utc") or {}
    return {
        "claimed": claimed,
        "no_claim": no_claim,
        "code": (claim or {}).get("delay_code"),
        "window": (hm(win.get("start")), hm(win.get("end"))) if win else None,
        "supported": sup,
        "supported_why": why,
        "family": pc.get("delay_code_family"),
        "basis": readable(pc.get("basis")),
        "difference": diff,
    }


def readable(text: str | None) -> str:
    """Backend sentences name milestones by id ('loading_complete observed ...'); show words."""
    if not text:
        return ""
    for name in MILESTONE_LABELS:
        text = text.replace(name, milestone_label(name).lower())
    text = text.replace("_", " ")
    return text[:1].upper() + text[1:]


def exposure(fig: dict, meta: dict) -> dict | None:
    """Penalty minutes not supported by the video × the contract SLA rate, when both exist."""
    rate = meta.get("sla_penalty_per_min")
    if rate is None or fig["difference"] is None:
        return None
    return {
        "amount": max(0, fig["difference"]) * float(rate),
        "rate": float(rate),
        "currency": meta.get("currency") or "",
    }


def outcome(fig: dict, meta: dict) -> dict:
    """The result of putting the airline's claim next to the video, in words both parties can
    read: not supported / partly supported / supported, or why it cannot be determined. Money
    is the claimed and supported minutes at the contract rate on file (synthetic in the demo).
    Derived only from figures the rule computed; never from a model answer."""
    claimed, sup = fig.get("claimed"), fig.get("supported")
    rate = meta.get("sla_penalty_per_min")
    cur = meta.get("currency") or ""
    money = None
    if rate is not None and claimed is not None and sup is not None:
        r = float(rate)
        money = {
            "claimed": claimed * r,
            "supported": int(sup) * r,
            "not_supported": max(0, claimed - int(sup)) * r,
            "rate": r,
            "currency": cur,
        }
    if fig.get("no_claim"):
        return {"kind": "no_claim", "label": "No claim to compare", "short": "No claim",
                "tone": "neutral", "text": "Attach the airline's claim to get a result.",
                "money": None}  # fmt: skip
    if sup is None:
        why = fig.get("supported_why") or "Not determined"
        return {"kind": "undetermined", "label": f"Cannot be determined · {why.lower()}",
                "short": why, "tone": "neutral", "text": fig.get("basis") or "", "money": None}  # fmt: skip
    sup = int(sup)
    if sup <= 0:
        kind, label, short, tone = (
            "not_supported",
            "Claim not supported by video",
            "Not supported",
            "good",
        )
        text = (
            f"None of the {claimed} claimed minutes fall while the event was still in progress. "
            "No penalty minutes are attributable to the handler for this event."
        )
    elif sup < claimed:
        kind, label, short, tone = (
            "partly_supported",
            "Claim partly supported",
            f"{sup} of {claimed} min",
            "warn",
        )
        text = (
            f"{sup} of the {claimed} claimed minutes fall while the event was still in progress; "
            f"{claimed - sup} do not. Penalty minutes attributable to the handler: {sup}."
        )
    else:
        kind, label, short, tone = "supported", "Claim supported by video", "Supported", "info"
        text = (
            f"All {claimed} claimed minutes fall while the event was still in progress. "
            f"Penalty minutes attributable to the handler: {claimed}."
        )
    if money:
        text += (
            f" At {money['currency']} {money['rate']:g}/min: {money['currency']} "
            f"{money['supported']:,.0f} supported, {money['currency']} "
            f"{money['not_supported']:,.0f} not supported (synthetic contract rate)."
        )
    return {
        "kind": kind,
        "label": label,
        "short": short,
        "tone": tone,
        "text": text,
        "money": money,
    }


def limitations(s: dict) -> list[str]:
    out = []
    ts = s.get("time_sync") or {}
    if ts.get("status") != "declared":
        out.append(
            "Clip has no declared start time: frame numbers only, no clock times or minutes."
        )
    if ts.get("speed_factor") and float(ts["speed_factor"]) != 1.0:
        src = (
            "estimated from vehicle motion"
            if "estimated" in str(ts.get("speed_factor_source"))
            else "declared"
        )
        out.append(
            f"Time-lapse footage (×{ts['speed_factor']:g}, {src}); times are converted with that factor."
        )
    for m in s.get("milestones") or []:
        if "present_at_clip_start" in m.get("method", ""):
            out.append(
                f"{milestone_label(m['name'])}: equipment already present when the clip starts (upper bound)."
            )
        if "cut_short" in m.get("method", ""):
            out.append(f"{milestone_label(m['name'])}: absence cut short by the clip end.")
    spark = s.get("spark") or {}
    if spark.get("ok") and spark.get("requires_operator_review"):
        out.append("Muse Spark flagged this event for operator review.")
    if spark.get("ok") and spark.get("hold_door_state") in (None, "unknown"):
        out.append("Hold-door state not visible from this camera.")
    ev = s.get("event") or {}
    if ev and not ev.get("validated", True):
        out.append("This event type has not been validated on real footage yet.")
    return out


def comparison_timeline(s: dict, claim: dict | None) -> dict | None:
    """Positions (0-100 %) for the claim window, video milestones and the handler log on one
    UTC axis. None when the clip is unsynced (no clock times to compare)."""
    if (s.get("time_sync") or {}).get("status") != "declared":
        return None
    points = []
    for m in s.get("milestones") or []:
        if m.get("t_utc"):
            points.append(("video", m["name"], m["t_utc"]))
    for h in s.get("handler_log") or []:
        if h.get("t_utc"):
            points.append(("log", h["milestone"], h["t_utc"]))
    win = (claim or {}).get("claim_window_utc") if not is_placeholder_claim(claim) else None
    times = [parse_t(t) for _, _, t in points]
    if win:
        times += [parse_t(win.get("start")), parse_t(win.get("end"))]
    times = [t for t in times if t]
    if len(times) < 2:
        return None
    lo, hi = min(times), max(times)
    span = (hi - lo).total_seconds() or 1.0
    pad = span * 0.06

    def pct(t: str | None) -> float:
        d = parse_t(t)
        return round(((d - lo).total_seconds() + pad) / (span + 2 * pad) * 100, 2) if d else 0.0

    marks = [
        {"kind": k, "name": n, "label": milestone_label(n), "t": hm(t), "x": pct(t)}
        for k, n, t in points
    ]
    window = None
    if win and win.get("start") and win.get("end"):
        x0, x1 = pct(win["start"]), pct(win["end"])
        window = {"x": x0, "w": max(0.5, x1 - x0), "start": hm(win["start"]), "end": hm(win["end"])}
    ticks = []
    first = lo.replace(second=0, microsecond=0)
    step = 300 if span <= 3600 else 900
    t = first
    while t <= hi:
        if t >= lo:
            ticks.append({"x": pct(t.isoformat()), "t": t.strftime("%H:%M")})
        t = datetime.fromtimestamp(t.timestamp() + step, tz=t.tzinfo)
    return {"marks": marks, "window": window, "ticks": ticks}


def activity(s: dict, claim: dict | None) -> list[dict]:
    """Operational events of the turnaround in clock order: video milestones, handler log and
    the claimed window. Unsynced milestones (no clock time) are listed last by frame."""
    rows = []
    for m in s.get("milestones") or []:
        how = (
            "Video evidence · SAM 3.1 rule"
            if m.get("method", "").startswith("sam31")
            else "Video evidence · Muse Spark"
        )
        if "present_at_clip_start" in m.get("method", ""):
            how += " · already present at clip start"
        rows.append({"t": m.get("t_utc"), "kind": "video", "title": milestone_label(m["name"]),
                     "sub": how + f" · frame {m.get('frame_index')}"})  # fmt: skip
    for h in s.get("handler_log") or []:
        rows.append({"t": h.get("t_utc"), "kind": "log", "title": milestone_label(h["milestone"]),
                     "sub": "Handler milestone log"})  # fmt: skip
    win = (claim or {}).get("claim_window_utc") if not is_placeholder_claim(claim) else None
    if win:
        rows.append({"t": win.get("start"), "kind": "claim", "title": "Claimed delay starts",
                     "sub": f"Airline claim · code {claim.get('delay_code')}, {claim.get('minutes')} min"})  # fmt: skip
        rows.append(
            {
                "t": win.get("end"),
                "kind": "claim",
                "title": "Claimed delay ends",
                "sub": "Airline claim",
            }
        )
    timed = sorted((r for r in rows if parse_t(r["t"])), key=lambda r: parse_t(r["t"]))
    return timed + [r for r in rows if not parse_t(r["t"])]


def case_key(meta: dict) -> str:
    return f"{meta.get('flight_number') or '?'}|{meta.get('flight_date') or ''}"


def primary_run(runs: list[dict]) -> dict:
    """The run a case is presented with: newest with computable minutes, else newest candidate,
    else newest. The other runs stay listed under the case."""
    for pred in (
        lambda r: (r.get("proposed") or {}).get("minutes_supported_by_video") is not None,
        lambda r: r.get("status") in ("candidate", "candidate_unsynced"),
        lambda r: True,
    ):
        hit = [r for r in runs if pred(r)]
        if hit:
            return hit[0]
    return runs[0]


def group_cases(cards: list[dict], claims: list[dict | None]) -> list[dict]:
    """cards: run_card() dicts newest first; claims: the airline claim stored with each run."""
    cases: dict[str, dict] = {}
    for c, cl in zip(cards, claims, strict=True):
        meta = c.get("meta") or {}
        k = case_key(meta)
        case = cases.setdefault(k, {"key": k, "meta": meta, "runs": [], "claim": None})
        case["runs"].append({**c, "claim": cl})
        if case["claim"] is None and cl and not is_placeholder_claim(cl):
            case["claim"] = cl
    out = []
    for case in cases.values():
        p = primary_run(case["runs"])
        case["primary"] = p
        case["status"] = p.get("evidence_status")
        case["review"] = review_label(p["review"]["state"])
        case["packets"] = [r for r in case["runs"] if r.get("packet_id")]
        case["sent"] = [r for r in case["runs"] if r["review"]["state"] in SENT_STATES]
        out.append(case)
    return out


def featured_case(cases: list[dict], key: str | None) -> dict | None:
    if not cases:
        return None
    if key:
        hit = next((c for c in cases if c["key"] == key), None)
        if hit:
            return hit
    ranked = [
        c
        for c in cases
        if (c["primary"].get("proposed") or {}).get("minutes_supported_by_video") is not None
    ]
    return (ranked or cases)[0]


def parse_verifier(output: str) -> list[dict]:
    """verify_packet.py prints one 'PASS|FAIL|SKIP  name  - detail' line per check."""
    rows = []
    for line in (output or "").splitlines():
        head = line[:4]
        if head in ("PASS", "FAIL", "SKIP"):
            name, _, detail = line[4:].strip().partition("  - ")
            rows.append({"status": head, "name": name.strip(), "detail": detail.strip()})
    return rows


# ---- turnaround chart -----------------------------------------------------------------------
# Lanes of real, timestamped records on one proportional axis. UTC when the footage has a
# declared start time; otherwise clip time (seconds into the clip), with the UTC records listed
# beside it instead of being projected onto footage that has no clock.
TICK_STEPS = (5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600)


class _Axis:
    def __init__(self, lo: float, hi: float, pad: float = 0.035):
        span = (hi - lo) or 60.0
        self.lo, self.hi = lo - span * pad, hi + span * pad

    def x(self, v: float) -> float:
        return round((v - self.lo) / (self.hi - self.lo) * 100, 2)

    def ticks(self, label) -> list[dict]:
        span = self.hi - self.lo
        step = next((s for s in TICK_STEPS if span / s <= 10), TICK_STEPS[-1])
        v, out = math.ceil(self.lo / step) * step, []
        while v <= self.hi:
            out.append({"x": self.x(v), "t": label(v, step)})
            v += step
        return out


def _epoch(t: str | None) -> float | None:
    d = parse_t(t)
    return d.timestamp() if d else None


def _clock(v: float, step: float) -> str:
    return datetime.fromtimestamp(v, UTC).strftime("%H:%M" if step >= 60 else "%H:%M:%S")


def _clip_clock(v: float, step: float) -> str:
    return f"{int(v // 60)}:{int(v % 60):02d}" if v >= 60 or step >= 60 else f"{v:g} s"


def _item(kind, label, tone, source, *, t=None, t1=None, time="", detail="", conf=None,
          unc_l="", unc_r="", frame=None) -> dict:  # fmt: skip
    return {"kind": kind, "label": label, "tone": tone, "source": source, "t": t, "t1": t1,
            "time": time, "detail": detail, "conf": conf, "unc_l": unc_l, "unc_r": unc_r,
            "frame": frame}  # fmt: skip


CHART_LABELS = {
    "loader_docked_start": "Equipment at hold",
    "loading_complete": "Loading complete",
    "hold_door_closed": "Hold door closed",
}


def _short(name: str) -> str:
    return CHART_LABELS.get(name) or milestone_label(name)


def _place(lanes: list[dict], axis: _Axis) -> None:
    """Percent positions; overlapping bars get their own row, and point labels a row each so
    close neighbours do not overlap."""
    for lane in lanes:
        ends: list[float] = []
        bar_ends: list[float] = []
        for it in sorted(lane["marks"], key=lambda i: i["t"]):
            it["x"] = axis.x(it["t"])
            it["row"] = 0
            if it["kind"] == "bar":
                it["w"] = max(0.6, axis.x(it["t1"]) - it["x"])
                row = next((r for r, e in enumerate(bar_ends) if it["t"] >= e), None)
                if row is None:
                    bar_ends.append(it["t1"])
                    row = len(bar_ends) - 1
                bar_ends[row] = it["t1"]
                it["row"] = row
            elif it["kind"] == "point":
                row = next((r for r, last in enumerate(ends) if it["x"] - last >= 12), None)
                if row is None:
                    ends.append(it["x"])
                    row = len(ends) - 1
                ends[row] = it["x"]
                it["row"] = row
            tip = [it["label"], it["time"], "Source: " + it["source"], it["detail"]]
            if it["conf"] is not None:
                tip.append(f"Rule confidence {it['conf']:.2f}")
            tip += [it["unc_l"], it["unc_r"]]
            it["tip"] = "\n".join(x for x in tip if x)
        lane["rows"] = len(ends)
        lane["brows"] = len(bar_ends)
        lane["marks"].sort(key=lambda i: (i["kind"] != "bar", i["t"]))


PROFILE_LABELS = {
    "aircraft": "Aircraft on stand",
    "persons": "Ground staff near aircraft",
}


def profile_lanes(profile: dict | None, synced: bool, event_used: str | None) -> list[dict]:
    """Extra camera-observed lanes from profile.json (SAM detections the pipeline already has):
    aircraft on stand, every event zone in the library, ground staff count. The lane that the
    packet's milestones come from is left out here (it is the main Camera-observed lane)."""
    if not profile:
        return []
    fps = profile.get("fps") or 24.0
    speed = profile.get("speed_factor")
    ref = profile.get("reference_start_utc")

    def at(frame: int) -> float | None:
        if synced:
            t = ref_time(ref, frame / fps, speed)
            return _epoch(t)
        return frame / fps

    def when(frame: int) -> str:
        if synced:
            return hm(ref_time(ref, frame / fps, speed)) + " UTC"
        return f"{frame / fps:.1f} s into clip"

    lanes = []
    for lane in profile.get("lanes", []):
        if lane.get("primary") or lane["key"] == event_used:
            continue
        validated = lane.get("validated", False)
        tone = (
            "aircraft"
            if lane["key"] == "aircraft"
            else ("staff" if lane["key"] == "persons" else ("video" if validated else "probe"))
        )
        marks = []
        for iv in lane.get("intervals", []):
            t0, t1 = at(iv["start"]), at(iv["end"])
            if t0 is None or t1 is None:
                continue
            label = lane["label"]
            detail = ""
            if lane["key"] == "persons":
                label = f"Ground staff · up to {iv.get('max_count', 0)}"
                detail = f"mean {iv.get('mean_count', 0)} persons in view"
            elif not validated:
                detail = "Zone defined in the event library; not yet validated on footage"
            marks.append(
                _item("bar", label, tone, lane.get("source", "SAM 3.1"), t=t0, t1=t1,
                      time=f"{when(iv['start'])} – {when(iv['end'])}".replace(" UTC –", " –"),
                      detail=detail, conf=iv.get("conf"),
                      unc_l="Already present when the footage starts." if iv.get("present_at_clip_start") else "",
                      unc_r="Still present when the footage ends." if iv.get("open") else "")
            )  # fmt: skip
        lanes.append({
            "key": "p-" + lane["key"],
            "label": lane["label"] + ("" if validated else " · unvalidated"),
            "marks": marks,
            "empty": "Not seen in this footage" if validated else "Not seen · zone not yet validated",
            "profile": True,
        })  # fmt: skip
    return lanes


def active_at(profile: dict | None, frame_index: int) -> list[dict]:
    """Which profile lanes are 'on' at a frame: the labels shown under the selected frame."""
    out = []
    for lane in (profile or {}).get("lanes", []):
        hit = next(
            (iv for iv in lane.get("intervals", []) if iv["start"] <= frame_index <= iv["end"]),
            None,
        )
        if hit is None:
            continue
        label = lane["label"]
        if lane["key"] == "persons":
            n = next((c for f, c in lane.get("series", []) if f >= frame_index), None)
            label = f"Ground staff · {n if n is not None else hit.get('max_count', 0)}"
        out.append({"key": lane["key"], "label": label, "validated": lane.get("validated", False)})
    return out


def turnaround_chart(
    s: dict,
    claim: dict | None,
    flight: dict | None = None,
    history: list[dict] | None = None,
    frames: list[dict] | None = None,
    profile: dict | None = None,
) -> dict | None:
    """Structured lanes for the turnaround chart, from the run summary, the airline claim, the
    flight-feed record (on/off-block) and the review history. Nothing is inferred: a lane with
    no records says so."""
    ts = s.get("time_sync") or {}
    src = s.get("source") or {}
    fps = src.get("fps") or 24.0
    dur = src.get("duration_s")
    ev = s.get("event") or {}
    names = ev.get("milestones") or {"start": "loader_docked_start", "end": "loading_complete"}
    ms = {m["name"]: m for m in s.get("milestones") or []}
    start_m, end_m = ms.get(names.get("start")), ms.get(names.get("end"))
    act_label = ev.get("label") or "Loading equipment at the hold"
    frame_of = {m["name"]: (m.get("evidence_frames") or [None])[0] for m in ms.values()}
    claim_ok = not is_placeholder_claim(claim)
    win = (claim or {}).get("claim_window_utc") if claim_ok else None
    synced = ts.get("status") == "declared"
    sam = "Camera · SAM 3.1 rule"

    def unc(m, end=False) -> str:
        meth = (m or {}).get("method", "")
        if not end and "present_at_clip_start" in meth:
            return "Already present when the footage starts: the true start is earlier."
        if end and "cut_short" in meth:
            return "The clear period after this point is cut short by the clip end."
        return ""

    # ---------- footage with a declared start: one UTC axis ----------
    if synced:
        ref, speed = ts.get("reference_start_utc"), ts.get("speed_factor")
        cov_end = ref_time(ref, dur, speed) if dur else None
        fl_items, cam_items, log_items, claim_items, rev_items = [], [], [], [], []
        if flight:
            src_f = "Airport flight feed" + (
                " (AODB file)" if flight.get("source") == "aodb_file" else ""
            )
            ob, offb = flight.get("on_block_utc"), flight.get("off_block_utc")
            if ob and offb:
                fl_items.append(_item("bar", f"On stand {flight.get('stand') or ''}".strip(), "flight",
                                      src_f, t=_epoch(ob), t1=_epoch(offb),
                                      time=f"{hm(ob)}–{hm(offb)} UTC"))  # fmt: skip
            for key, lbl in (("landed_utc", "Landed"), ("on_block_utc", "On-block"),
                             ("off_block_utc", "Off-block")):  # fmt: skip
                if flight.get(key):
                    fl_items.append(_item("point", lbl, "flight", src_f, t=_epoch(flight[key]),
                                          time=hm(flight[key]) + " UTC"))  # fmt: skip
        if cov_end:
            cam_items.append(_item("bar", "Footage coverage", "coverage", "Camera footage",
                                   t=_epoch(ref), t1=_epoch(cov_end),
                                   time=f"{hm(ref)}–{hm(cov_end)} UTC",
                                   detail=f"{dur:g} s of footage"
                                   + (f" at ×{speed:g} time-lapse" if speed and speed != 1 else "")))  # fmt: skip
        a0 = (start_m or {}).get("t_utc")
        a1 = (end_m or {}).get("t_utc") or (cov_end if a0 else None)
        if a0 and a1:
            cam_items.append(_item("bar", act_label, "video", sam, t=_epoch(a0), t1=_epoch(a1),
                                   time=f"{hm(a0)}–{hm(a1)} UTC" + ("" if end_m else " (open)"),
                                   unc_l=unc(start_m),
                                   unc_r="" if end_m else "Still present when the footage ends.",
                                   frame=frame_of.get(names.get("end")) or frame_of.get(names.get("start"))))  # fmt: skip
        for m in ms.values():
            if m.get("t_utc"):
                cam_items.append(_item("point", _short(m["name"]), "video", sam,
                                       t=_epoch(m["t_utc"]), time=hm(m["t_utc"]) + " UTC",
                                       detail=f"frame {m.get('frame_index')}", conf=m.get("confidence"),
                                       unc_l=unc(m, m is end_m), frame=frame_of.get(m["name"])))  # fmt: skip
        milestone_frames = {f for f in frame_of.values() if f}
        for f in frames or []:
            if f.get("kind") == "evidence" and f["id"] not in milestone_frames and f.get("t_utc"):
                cam_items.append(_item("tick", f.get("title") or "Evidence frame", "video",
                                       "Signed evidence frame", t=_epoch(f["t_utc"]),
                                       time=hm(f["t_utc"]) + " UTC", detail=f.get("phase", ""),
                                       frame=f["id"]))  # fmt: skip
        for h in s.get("handler_log") or []:
            if h.get("t_utc"):
                log_items.append(_item("point", _short(h["milestone"]), "log",
                                       "Handler milestone log", t=_epoch(h["t_utc"]),
                                       time=hm(h["t_utc"]) + " UTC"))  # fmt: skip
        if win and win.get("start") and win.get("end"):
            claim_items.append(_item("bar", f"Claimed delay · code {claim.get('delay_code')} · "
                                     f"{claim.get('minutes')} min", "claim", "Airline delay claim",
                                     t=_epoch(win["start"]), t1=_epoch(win["end"]),
                                     time=f"{hm(win['start'])}–{hm(win['end'])} UTC",
                                     detail=str(claim.get("source") or "")))  # fmt: skip
        times = [i[k] for g in (fl_items, cam_items, log_items, claim_items)
                 for i in g for k in ("t", "t1") if i[k] is not None]  # fmt: skip
        if len(times) < 2:
            return None
        lo, hi = min(times), max(times)
        later = []
        for h in history or []:
            e = _epoch(h.get("t_utc"))
            if e is None:
                continue
            if lo - 600 <= e <= hi + 600:
                rev_items.append(_item("point", review_label(h.get("to")).get("label"), "review",
                                       "Review decision · " + str(h.get("actor", "")).replace("_", " "),
                                       t=e, time=hm(h["t_utc"]) + " UTC", detail=h.get("note") or ""))  # fmt: skip
            else:
                later.append(h)
        lanes = [
            {"key": "flight", "label": "Aircraft / flight", "marks": fl_items,
             "empty": "No flight-feed record for this flight"},
            {"key": "video", "label": "Camera-observed", "marks": cam_items,
             "empty": "No timed observation"},
            *profile_lanes(profile, True, (ev.get("name") or "loading")),
            {"key": "log", "label": "Handler log", "marks": log_items,
             "empty": "No handler milestones on file"},
            {"key": "claim", "label": "Airline claim", "marks": claim_items,
             "empty": "No claim window" if claim_ok else "No airline claim on file"},
        ]  # fmt: skip
        if rev_items or later:
            lanes.append({"key": "review", "label": "Review", "marks": rev_items,
                          "empty": (f"{len(later)} decision{'s' if len(later) != 1 else ''} recorded "
                                    f"{day(later[0]['t_utc'])}, after the turnaround")
                          if later else ""})  # fmt: skip
        axis = _Axis(lo, hi)
        _place(lanes, axis)
        fx = {}
        for f in frames or []:
            e = _epoch(f.get("t_utc"))
            if e is not None and axis.lo <= e <= axis.hi:
                fx[f["id"]] = axis.x(e)
        return {"mode": "utc", "lanes": lanes, "ticks": axis.ticks(_clock), "frames": fx,
                "span": f"{_clock(lo, 60)}–{_clock(hi, 60)} UTC", "outside": []}  # fmt: skip

    # ---------- footage without a clock: clip time only ----------
    end_s = dur or max(((m.get("frame_index") or 0) / fps for m in ms.values()), default=0)
    if not end_s:
        return None
    cam_items = [_item("bar", "Footage (no clock time)", "coverage", "Camera footage",
                       t=0.0, t1=float(end_s), time=f"0–{end_s:.1f} s",
                       detail="No declared start time: not comparable with UTC records")]  # fmt: skip
    if start_m:
        a1 = (end_m["frame_index"] / fps) if end_m else float(end_s)
        cam_items.append(_item("bar", act_label, "video", sam, t=start_m["frame_index"] / fps, t1=a1,
                               time=f"{start_m['frame_index'] / fps:.1f}–{a1:.1f} s"
                               + ("" if end_m else " (open)"), unc_l=unc(start_m),
                               unc_r="" if end_m else "Still present when the footage ends.",
                               frame=frame_of.get(names.get("end")) or frame_of.get(names.get("start"))))  # fmt: skip
    for m in ms.values():
        sec = (m.get("frame_index") or 0) / fps
        cam_items.append(_item("point", _short(m["name"]), "video", sam, t=sec,
                               time=f"{sec:.1f} s into clip", detail=f"frame {m.get('frame_index')}",
                               conf=m.get("confidence"), unc_l=unc(m, m is end_m),
                               frame=frame_of.get(m["name"])))  # fmt: skip
    milestone_frames = {f for f in frame_of.values() if f}
    for f in frames or []:
        if f.get("kind") == "evidence" and f["id"] not in milestone_frames:
            cam_items.append(_item("tick", f.get("title") or "Evidence frame", "video",
                                   "Signed evidence frame", t=f["t_s"],
                                   time=f"{f['t_s']:.1f} s into clip", detail=f.get("phase", ""),
                                   frame=f["id"]))  # fmt: skip
    lanes = [{"key": "video", "label": "Camera-observed", "marks": cam_items, "empty": ""}]
    lanes += profile_lanes(profile, False, (ev.get("name") or "loading"))
    axis = _Axis(0.0, float(end_s), pad=0.02)
    _place(lanes, axis)
    outside = []
    if flight:
        for key, lbl in (("on_block_utc", "On-block"), ("off_block_utc", "Off-block")):
            if flight.get(key):
                outside.append({"label": lbl, "t": hm(flight[key]), "source": "Flight feed"})
    for h in s.get("handler_log") or []:
        if h.get("t_utc"):
            outside.append({"label": _short(h["milestone"]), "t": hm(h["t_utc"]),
                            "source": "Handler log"})  # fmt: skip
    if win and win.get("start") and win.get("end"):
        outside.append({"label": "Claimed delay", "t": f"{hm(win['start'])}–{hm(win['end'])}",
                        "source": "Airline claim"})  # fmt: skip
    fx = {f["id"]: axis.x(f["t_s"]) for f in frames or [] if f.get("t_s") is not None}
    return {"mode": "clip", "lanes": lanes, "ticks": axis.ticks(_clip_clock), "frames": fx,
            "span": f"clip time 0–{end_s:.0f} s", "outside": outside}  # fmt: skip


def frame_phase(idx: int, s: dict) -> str:
    """Where a frame sits relative to the detected activity (from the stored milestones)."""
    ev = s.get("event") or {}
    names = ev.get("milestones") or {"start": "loader_docked_start", "end": "loading_complete"}
    ms = {m["name"]: m for m in s.get("milestones") or []}
    st, en = ms.get(names.get("start")), ms.get(names.get("end"))
    if en and idx >= en.get("frame_index", 0):
        return "After " + milestone_label(en["name"]).lower()
    if st and idx >= st.get("frame_index", 0):
        return "Within the detected activity"
    return "Before the detected activity" if st else ""
