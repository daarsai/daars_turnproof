# TurnProof demo script — three turnarounds, three outcomes

Everything below is typed into the console by hand during the recording. Nothing is pre-loaded:
the console starts with no claims and no runs, the airline's message is registered in
**New Claim**, the footage is uploaded in **Upload Footage**, and every decision is made in the
console. All flight, claim and log values are **synthetic test data on licensed footage**; the
contract rate (EUR 40 per minute) is a synthetic placeholder for an SGHA Annex B rate.

| Case | Footage | What the video shows | Outcome |
|---|---|---|---|
| A · XY123 | clip1.mp4 | loading finished 3.5 min **before** the claimed window | **Claim not supported** — no penalty |
| B · XY456 | clip1.mp4 | loading finished 4 min **into** the claimed window | **Claim partly supported** — 4 of 12 min stand |
| C · XY789 | clip3.mp4 | loader still at the hold when the footage ends | **Cannot be determined** — no minutes invented |

The dataset, plainly: of the three licensed clips only clip1 contains a complete
docked → departed cycle (equipment present at the start, leaves after 35 s of video, ×6
time-lapse). clip2 and clip3 show equipment that never leaves inside the clip, so they can only
produce the third outcome. That is why A and B use the same clip with different declared start
times and claims — which is exactly how the rule works in production: the camera clock and the
claim window decide where the minutes land. Say it in the demo ("same footage, two claims");
it is honest and it is the clearer story. Case C is not a weakness to hide: it shows the tool
refusing to invent minutes it cannot see, which is the property an airline needs before it
trusts the other two.

Every value below is also in `config/demo_cases.json`. `scripts/run_demo_cases.py` registers the
claims and uploads the footage for you (`--print` shows the values to type); the decisions
stay manual — they are the demo.

Model cost per replay: SAM 3.1 is served from the cache (same file bytes, $0); the Muse Spark
keyframe check runs once per upload and the Spark claim extraction once per message pasted
into New Claim (a few cents each).

## 0. Start from zero

Terminal, in the project folder:

```bash
make reset-demo                   # runs, claims, uploads, deliveries -> data/archive/<timestamp>/ (cache kept)
make serve                        # console on http://127.0.0.1:8090 (MODEL_API_KEY from .env; Spark needs it)
```

Open http://127.0.0.1:8090/ as **Ground Handler** (top-right menu). Overview shows "No evidence
yet", Claims is empty, Airport & Cameras shows the day's flights (XY123 on D14, XY456 on D16,
XY789 on C02 without a camera).

Shortcut when you do not need to show the typing: in a second terminal
`python scripts/run_demo_cases.py` registers all three claims and uploads the footage
(`--cases A` for one case). Then continue at A3.

## Case A — XY123: claim not supported (no penalty)

Flight XY123, XY Airways, BLR stand D14, 30 Oct 2026. On-block 17:58, STD 18:45,
off-block 18:54 (9 minutes late). The airline codes the delay 32 (loading) against the handler.

### A1. Register the claim — Claims › New Claim

Paste as the airline message:

```
DLA
XY123/30OCT VTABC BLR
STD 1845Z ATD 1854Z
DLA/32/0009 LOADING - HANDLER
SI LOADING EQUIPMENT STILL AT FWD HOLD AT STD, STAND D14
```

**Extract with Muse Spark**, then check every field (the telex parser cross-checks code,
minutes, flight and STD/ATD):

| Field | Value |
|---|---|
| Flight number · date · airline · airport | XY123 · 2026-10-30 · XY Airways · BLR |
| Stand · camera | D14 · stand-d14-01 |
| Delay code · claimed minutes | 32 · 9 |
| Claimed delay starts / ends (UTC) | 2026-10-30 18:45:00 / 2026-10-30 18:54:00 |
| Your milestone log: loader docked / loading complete / hold door closed | 18:20:00 / 18:41:00 / 18:42:00 (all 2026-10-30) |
| Contract and parties | Handler Co · 40 per minute · EUR |

**Confirm claim → Add Evidence.** The upload page opens with the claim preselected.

### A2. Upload the footage — Upload Footage

| Field | Value |
|---|---|
| Footage | `clips/clip1.mp4` (from the main folder's `clips/`) |
| Claim this footage belongs to | XY123 · XY Airways · 2026-10-30 · BLR stand D14 · claim code 32, 9 min |
| Event to detect | Loading equipment at the hold |
| Camera view | Front quarter |
| Clip start time (UTC) | 2026-10-30 18:38:00 |
| Speed factor · how known | 6.0 · estimated from vehicle motion |
| Muse Spark keyframe check | on |

**Upload and analyze.** The processing page shows the stages (ingest → SAM 3.1 → redact → rule
→ Spark → packet); about a minute from the cache.

### A3. What the console shows

- Evidence Review: **Loading complete 18:41:30 UTC** (frame 1050), loader already at the hold
  when the clip starts ("by 18:38:00").
- Claim vs Evidence: claimed **9 min**, supported by video **0 min**.
- Outcome box: **Claim not supported by video** — none of the 9 claimed minutes fall while
  loading was in progress; EUR 0 supported, **EUR 360 not supported**.
- Turnaround Timeline: aircraft on stand, loading equipment lane ending at 18:41:30, the
  airline's claim window 18:45–18:54 to the right of it, handler log circles, ground-staff
  lane; the fuel-truck and catering lanes read "not seen · zone not validated".
- Handler log comparison: video 18:41:30 vs log 18:41 → +0.5 min, consistent.

### A4. Decide and send (Ground Handler)

1. Operator statement (optional, signed into the packet): record or type
   *"Loader left the forward hold at 18:41, three and a half minutes before STD. Claim not accepted."*
2. **Confirm** with a note (Spark flags every event for operator review, so a note is required):
   *"Checked the departure frames; zone clear from 18:41:30."*
3. **Send to airline.** The packet is re-issued as a new signed version carrying the decision,
   the note and the statement; the webhook delivery shows under Sent Packets.

### A5. Airline side

Switch to **Airline** (top-right). Received Cases shows XY123 with **Not supported · Sent to
airline**. Open it, click **Verify** (7 checks pass), then **Acknowledge** with the note
*"Accepted. Claim withdrawn."* The packet is re-issued again with the airline's answer; Case
Responses lists the signed delivery.

## Case B — XY456: claim partly supported (the penalty stands for 4 of 12 minutes)

Flight XY456, XY Airways, BLR stand D16, 30 Oct 2026. On-block 19:10, STD 19:55,
off-block 20:07 (12 minutes late), coded 32 against the handler. This time the loader is
still at the hold when the scheduled departure time passes.

### B1. Register the claim — Claims › New Claim

```
MVT
XY456/30.VTDEF.BLR
AD2007/2018 EA2135 DEL
DL32/0012
SI STD 1955Z - LATE LOADING STAND D16
```

| Field | Value |
|---|---|
| Flight number · date · airline · airport | XY456 · 2026-10-30 · XY Airways · BLR |
| Stand · camera | D16 · stand-d16-01 |
| Delay code · claimed minutes | 32 · 12 |
| Claimed delay starts / ends (UTC) | 2026-10-30 19:55:00 / 2026-10-30 20:07:00 |
| Your milestone log: loader docked / loading complete / hold door closed | 19:35:00 / 19:58:00 / 19:59:30 |
| Contract and parties | Handler Co · 40 per minute · EUR |

### B2. Upload the footage

Same clip and settings as A2, except **Claim: XY456 …** and **Clip start time (UTC):
2026-10-30 19:55:30**.

### B3. What the console shows

- **Loading complete 19:59:00 UTC**, four minutes after the claimed window opened at 19:55.
- Claimed **12 min**, supported by video **4 min**, difference 8 min.
- Outcome box: **Claim partly supported** — 4 of the 12 claimed minutes fall while loading
  was in progress, 8 do not. **EUR 160 supported, EUR 320 not supported.**
- Handler log comparison: the handler's own log said 19:58; the video says 19:59:00
  (+1.0 min). The tool is neutral: it also corrects the handler.

### B4. Decide and send

Confirm with the note *"Loader still at the hold at STD; 4 minutes are ours, 8 are not."*,
then **Send to airline**. On the airline side the case shows **4 of 12 min**. Two endings work
for the demo:

- **Acknowledge** — the airline accepts 4 minutes instead of 12 (EUR 160 instead of EUR 480).
- **Dispute** with a note — then back as Ground Handler, **Resolve** with a note once both
  sides agree. Every step is in the decision history and the hash-chained event log.

## Case C — XY789: cannot be determined (the footage does not show the end)

Flight XY789, XY Airways, BLR stand C02, 30 Oct 2026. On-block 17:50, STD 18:25, off-block
18:35 (10 minutes late), coded 32 against the handler. The stand has no registered camera
(Airport & Cameras lists it as an exception); the footage is a handheld clip the ramp
supervisor uploaded.

### C1. Register the claim — Claims › New Claim

```
DLA
XY789/30OCT VTGHI BLR
STD 1825Z ATD 1835Z
DLA/32/0010 LOADING - HANDLER
SI LOADER STILL AT HOLD AFTER STD, STAND C02
```

| Field | Value |
|---|---|
| Flight number · date · airline · airport | XY789 · 2026-10-30 · XY Airways · BLR |
| Stand · camera | C02 · stand-c02-01 |
| Delay code · claimed minutes | 32 · 10 |
| Claimed delay starts / ends (UTC) | 2026-10-30 18:25:00 / 2026-10-30 18:35:00 |
| Your milestone log: loader docked / loading complete / hold door closed | 18:22:00 / 18:30:00 / 18:31:00 |
| Contract and parties | Handler Co · 40 per minute · EUR |

### C2. Upload the footage

`clips/clip3.mp4` · event Loading equipment at the hold · view Front quarter · **clip start
2026-10-30 18:20:00** · speed factor **12.0**, estimated from vehicle motion · Spark on.

### C3. What the console shows

- Evidence: **No complete event detected** — equipment still in the zone when the clip ends.
- Supported by video: **Insufficient evidence**; outcome **Cannot be determined**. No money
  figure, because none can be computed.
- The handler's log says loading completed at 18:30; the video cannot confirm it. Nothing to
  confirm, nothing is sent. Narration: "TurnProof does not help the handler here, and that is
  the point — it only signs what the camera saw."

## If something differs on the day

- Muse Spark disagrees with the rule (rare): the outcome reads "cannot be determined ·
  operator decision required". That is the designed behaviour — the operator reviews the
  frames and uses **Correct** or **Confirm** with a note, and the packet records that a human
  decided.
- The "Loading complete" time moves by a few seconds if the cache is cold and SAM is
  re-queried (new boxes, same footage); the minute figures above do not change.
- A missed field in New Claim can be fixed by registering the claim again; the earlier one
  stays listed until `make reset-demo`.

The recording plan for the video is in `docs/DEMO_STORYBOARD.md`.
