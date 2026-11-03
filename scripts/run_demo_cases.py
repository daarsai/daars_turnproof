"""Register the demo claims and upload their footage through the running console.

Does exactly what an operator does in New Claim and Upload Footage, with the values from
config/demo_cases.json, so a demo can be set up in one command. The decisions (confirm, send,
acknowledge, dispute) are NOT made here: they are the part of the demo that is shown by hand.

    python scripts/run_demo_cases.py                      # cases A, B, C against http://127.0.0.1:8090
    python scripts/run_demo_cases.py --cases A,B --clips clips
    python scripts/run_demo_cases.py --print              # show the values to type, run nothing

Cost: SAM 3.1 is served from the cache for footage analysed before ($0); the Muse Spark
keyframe check runs once per upload (a few cents). The Spark claim extraction is skipped here
(the claim values are confirmed from the file); use New Claim in the console to show it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx


def load_cases(path: Path, wanted: str | None) -> list[dict]:
    cases = json.loads(path.read_text())["cases"]
    if wanted:
        ids = {w.strip().upper() for w in wanted.split(",")}
        cases = [c for c in cases if c["id"].upper() in ids]
    return cases


def show(case: dict) -> None:
    print(f"\n=== Case {case['id']}: {case['title']}")
    print("Airline message (New Claim):")
    print("  " + case["message"].replace("\n", "\n  "))
    f, cl, lg, ct, up = case["flight"], case["claim"], case["log"], case["contract"], case["upload"]
    print(f"Flight: {f['flight_number']} · {f['flight_date']} · {f['airline']} · {f['station']} stand "
          f"{f['stand']} · camera {f['camera_id']} · handler {f['handler']}")  # fmt: skip
    print(
        f"Claim: code {cl['delay_code']}, {cl['minutes']} min, window {cl['window_start']} -> {cl['window_end']} UTC"
    )
    print(f"Log: docked {lg['log_docked']} · complete {lg['log_complete']} · door {lg['log_door']}")
    print(f"Contract: {ct['sla_rate']} {ct['currency']} per minute")
    print(f"Upload: {case['clip']} · event {up['event']} · view {up['view']} · clip start "
          f"{up['reference_start']} UTC · speed x{up['speed_factor']} ({up['speed_source']})")  # fmt: skip
    if e := case.get("expected"):
        print(f"Expected: {e['outcome']} · supported {e['supported_minutes']} min · {e['money']}")


def register(client: httpx.Client, case: dict) -> str:
    f, cl, lg, ct = case["flight"], case["claim"], case["log"], case["contract"]
    data = {
        **f,
        "delay_code": cl["delay_code"],
        "minutes": str(cl["minutes"]),
        "window_start": cl["window_start"],
        "window_end": cl["window_end"],
        **lg,
        "sla_rate": str(ct["sla_rate"]),
        "currency": ct["currency"],
        "message": case["message"],
        "message_type": case.get("message_type", "telex"),
    }
    r = client.post("/intake/confirm", data=data, follow_redirects=False)
    if r.status_code != 303 or "scenario=" not in r.headers.get("location", ""):
        raise SystemExit(f"claim registration failed ({r.status_code}): {r.text[:200]}")
    return r.headers["location"].split("scenario=")[1].split("&")[0]


def upload(client: httpx.Client, case: dict, clip: Path, scenario: str) -> str:
    up = case["upload"]
    data = {
        "scenario": scenario,
        "event": up["event"],
        "view": up["view"],
        "reference_start": up["reference_start"],
        "speed_factor": str(up["speed_factor"]),
        "speed_source": up["speed_source"],
    }
    if up.get("use_spark", True):
        data["use_spark"] = "on"
    with clip.open("rb") as fh:
        r = client.post(
            "/upload",
            data=data,
            files={"clip": (clip.name, fh, "video/mp4")},
            follow_redirects=False,
            timeout=600,
        )
    if r.status_code != 303 or "/runs/" not in r.headers.get("location", ""):
        raise SystemExit(f"upload failed ({r.status_code}): {r.text[:200]}")
    return r.headers["location"].split("/runs/")[1].split("?")[0]


def wait(client: httpx.Client, run_id: str, timeout_s: int = 1800) -> dict:
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout_s:
        st = client.get(f"/api/runs/{run_id}/status").json()
        if st.get("stage") != last:
            last = st.get("stage")
            print(f"  {run_id}: {last}", flush=True)
        if st.get("state") in ("done", "failed"):
            return st
        time.sleep(2)
    raise SystemExit(f"timeout waiting for {run_id}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--server", default="http://127.0.0.1:8090")
    ap.add_argument("--cases", default=None, help="comma-separated ids, e.g. A,B (default: all)")
    ap.add_argument("--clips", default="clips", help="folder holding the footage files")
    ap.add_argument("--config", default="config/demo_cases.json")
    ap.add_argument("--print", action="store_true", help="print the values to type; run nothing")
    args = ap.parse_args()
    cases = load_cases(Path(args.config), args.cases)
    if not cases:
        raise SystemExit("no matching cases")
    for case in cases:
        show(case)
    if args.print:
        return
    missing = [c["clip"] for c in cases if not (Path(args.clips) / c["clip"]).exists()]
    if missing:
        raise SystemExit(f"footage not found in {args.clips}/: {', '.join(missing)}")
    with httpx.Client(base_url=args.server, cookies={"tp_role": "handler"}, timeout=60) as client:
        try:
            client.get("/").raise_for_status()
        except httpx.HTTPError as e:
            raise SystemExit(f"console not reachable at {args.server}: {e}") from e
        results = []
        for case in cases:
            print(f"\n--- running case {case['id']}")
            scen = register(client, case)
            print(f"  claim registered: {scen}")
            run_id = upload(client, case, Path(args.clips) / case["clip"], scen)
            st = wait(client, run_id)
            if st.get("state") != "done":
                print(f"  FAILED: {st.get('error')}")
                results.append((case["id"], run_id, "failed", None))
                continue
            s = client.get(f"/api/runs/{run_id}").json()
            pc = s.get("proposed_claim") or {}
            lc = next((m for m in s.get("milestones", []) if m["name"].endswith("_complete")), None)
            results.append(
                (case["id"], run_id, s.get("status"), pc.get("minutes_supported_by_video"))
            )
            print(f"  done: status {s.get('status')} · completion {(lc or {}).get('t_utc')} · "
                  f"supported {pc.get('minutes_supported_by_video')} min · {pc.get('basis')} · "
                  f"est. cost ${(s.get('metrics') or {}).get('est_cost_usd')}")  # fmt: skip
            print(f"  open: {args.server}/runs/{run_id}")
    print("\nSummary")
    for cid, rid, status, sup in results:
        print(f"  case {cid}: run {rid} · {status} · supported {sup}")
    print(
        "Next: Evidence Review in the console -> confirm and send each case by hand; then the airline side."
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
