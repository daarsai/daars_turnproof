# TurnProof demo script — three turnarounds, three outcomes

Everything below is typed into the console by hand. Nothing is pre-loaded: the console starts
with no claims and no runs, the airline's message is registered in **New Claim**, the footage is
uploaded in **Upload Footage**, and every decision is made in the console. All flight, claim and
log values are **synthetic test data on licensed footage**; the contract rate (EUR 40 per minute)
is a synthetic placeholder for an SGHA Annex B rate.

| Case | Footage | What the video shows | Outcome |
|---|---|---|---|
| A · XY123 | clip1.mp4 | loading still in progress for the whole 3-minute claimed window | **Claim supported** — 3 of 3 min stand |
| B · XY456 | clip3.mp4 | loading finished 2 min **into** the 12-minute claimed window | **Claim partly supported** — 2 of 12 min stand |
| C · XY789 | clip2.mp4 | equipment still at the hold when the footage ends | **Cannot be determined** — no minutes invented |

The dataset, plainly: three licensed time-lapse clips. clip1 shows equipment already at the
hold at the start that leaves after 35 s of video (frame 1050, ×6). clip3, with a declared start
time and ×12, shows equipment docking at frame 30 and the zone clear from frame 420 until the clip
ends (the departure is flagged as cut short by the clip end). clip2 shows equipment that never
leaves inside the clip, so it can only produce the third outcome. The camera clock and the claim
window decide where the minutes land; the declared start times below are what place each clip on
its flight's clock.

Every value below is also in `config/demo_cases.json`. `scripts/run_demo_cases.py` registers the
claims and uploads the footage for you (`--print` shows the values to type); the decisions
stay manual. The signed packets these cases produced are in `examples/`.

Model cost per replay: SAM 3.1 is served from the cache (same file bytes, $0); the Muse Spark
keyframe check is served from its cache when the same frames were checked before, otherwise it
runs once per upload; the Spark claim extraction runs once per message pasted into New Claim
(a few cents each).

## 0. Start from zero

Terminal, in the project folder:

```bash
make reset-demo                   # runs, claims, uploads, deliveries -> data/archive/<timestamp>/ (cache kept)
make serve                        # console on http://127.0.0.1:8090 (MODEL_API_KEY from .env; Spark needs it)
```

Open http://127.0.0.1:8090/ as **Ground Handler** (top-right menu). Overview shows "No evidence
yet", Claims is empty, Airport & Cameras shows the day's flights (XY123 on D14, XY456 on D16,
XY789 on C02 without a registered camera).

Shortcut when you do not need to show the typing: in a second terminal
`python scripts/run_demo_cases.py` registers all three claims and uploads the footage
(`--cases A` for one case). Then continue at A3.

## Case A — XY123: claim supported (the penalty stands)

Flight XY123, XY Airways, BLR stand D14, 30 Oct 2026. STD 18:45, ATD 18:48 (3 minutes late),
coded 32 (loading) against the handler. The handler's log says loading was complete at 18:44.

### A1. Register the claim — Claims › New Claim

Paste as the airline message:

```
DLA
XY123/30OCT VTABC BLR
STD 1845Z ATD 1848Z
DLA/32/0003 LOADING - HANDLER
SI LOADING EQUIPMENT NOT CLEARED FROM FWD HOLD BY STD, STAND D14
```

**Extract with Muse Spark**, then check every field (the telex parser cross-checks code,
minutes, flight and STD/ATD):

| Field | Value |
|---|---|
| Flight number · date · airline · airport | XY123 · 2026-10-30 · XY Airways · BLR |
| Stand · camera | D14 · stand-d14-01 |
| Delay code · claimed minutes | 32 · 3 |
| Claimed delay starts / ends (UTC) | 2026-10-30 18:45:00 / 2026-10-30 18:48:00 |
| Your milestone log: loader docked / loading complete / hold door closed | 18:20:00 / 18:44:00 / 18:45:00 (all 2026-10-30) |
| Contract and parties | Handler Co · 40 per minute · EUR |

**Confirm claim → Add Evidence.** The upload page opens with the claim preselected.

### A2. Upload the footage — Upload Footage

| Field | Value |
|---|---|
| Footage | `clips/clip1.mp4` |
| Claim this footage belongs to | XY123 · XY Airways · 2026-10-30 · BLR stand D14 · claim code 32, 3 min |
| Event to detect | Loading equipment at the hold |
| Camera view | Front quarter |
| Clip start time (UTC) | 2026-10-30 18:44:45 |
| Speed factor · how known | 6.0 · estimated from vehicle motion |
| Muse Spark keyframe check | on |

**Upload and analyze.** The processing page shows the stages (ingest → SAM 3.1 → redact → rule
→ Spark → packet); about a minute from the cache.

### A3. What the console shows

- Evidence Review: **Loading complete 18:48:15 UTC** (frame 1050, 35.0 s into the clip);
  loading equipment already at the hold when the clip starts ("by 18:44:45").
- Claim vs Evidence: claimed **3 min**, supported by video **3 min**, difference 0 min.
- Outcome box: **Claim supported by video** — all 3 claimed minutes fall while loading was
  still in progress; EUR 120 attributable to the handler.
- Handler log comparison: the log says loading complete 18:44; the video says 18:48:15
  (+4.3 min). The camera contradicts the handler's own log.

### A4. Decide and send (Ground Handler)

1. Operator statement (optional, signed into the packet): type it, or record it with the
   microphone (transcribed by Muse Voice Transcribe).
2. **Confirm** with a note (Spark flags every event for operator review, so a note is required):
   *"Departure frames checked; zone clear only from 18:48:15. Accepting 3 minutes."*
3. **Send to airline.** The packet is re-issued as a new signed version carrying the decision,
   the note and the statement; the webhook delivery shows under Sent Packets.

### A5. Airline side

Switch to **Airline** (top-right). Open XY123, click **Verify** (7 checks pass), then
**Acknowledge** with the note *"Accepted. 3 minutes confirmed by video."* The packet is re-issued
again with the airline's answer.

## Case B — XY456: claim partly supported (2 of 12 minutes stand)

Flight XY456, XY Airways, BLR stand D16, 30 Oct 2026. STD 19:57, departure 20:09 (12 minutes
late), coded 32 against the handler.

### B1. Register the claim — Claims › New Claim

```
MVT
XY456/30.VTDEF.BLR
AD2009/2020 EA2135 DEL
DL32/0012
SI SERVICE VEHICLE REMAINED AT HOLD WELL PAST STD 1957Z STAND D16
```

Muse Spark extracts flight, code and minutes; the MVT does not carry the flight date or the
claimed window, so complete them by hand:

| Field | Value |
|---|---|
| Flight number · date · airline · airport | XY456 · 2026-10-30 · XY Airways · BLR |
| Stand · camera | D16 · stand-d16-01 |
| Delay code · claimed minutes | 32 · 12 |
| Claimed delay starts / ends (UTC) | 2026-10-30 19:57:00 / 2026-10-30 20:09:00 |
| Your milestone log: loader docked / loading complete / hold door closed | 19:35:00 / 19:58:00 / 19:59:30 |
| Contract and parties | Handler Co · 40 per minute · EUR |

### B2. Upload the footage

`clips/clip3.mp4` · claim XY456 · event Loading equipment at the hold · view Front quarter ·
**clip start 2026-10-30 19:56:12** · speed factor **12.0**, estimated from vehicle motion ·
Spark on.

### B3. What the console shows

- Loading equipment at the hold from **19:56:24** (frame 30); **loading complete 19:59:00 UTC**
  (frame 420; the absence is cut short by the clip end), two minutes after the claimed window
  opened at 19:57.
- Claimed **12 min**, supported by video **2 min**, difference 10 min.
- Outcome box: **Claim partly supported** — EUR 480 claimed, EUR 80 supported, EUR 400 not
  supported.
- Handler log comparison: loading complete 19:58 in the log, 19:59:00 on video (+1.0 min).
- Muse Spark agrees the equipment departed and flags the event for operator review.

### B4. Decide, send, dispute, resolve

1. **Confirm** with the note *"Loader still at the hold at STD; 2 minutes are ours, 10 are
   not."*, then **Send to airline**.
2. Airline: **Verify** (7 checks pass), then **Dispute** with the note *"We recorded the vehicle
   at the hold until 20:07. Request full 12 minutes."*
3. Ground Handler: **Resolve** with the note *"Camera-timed departure 19:59:00, signed packet.
   2 minutes accepted, 10 declined."* The resolution is recorded in the review record and the
   hash-chained event log; the latest signed packet reflects the airline's dispute.

## Case C — XY789: cannot be determined (the footage does not show the end)

Flight XY789, XY Airways, BLR stand C02, 30 Oct 2026. STD 18:25, ATD 18:35 (10 minutes late),
coded 32 against the handler. Airport & Cameras lists stand C02 as an exception: no camera
registered.

### C1. Register the claim — Claims › New Claim

```
DLA
XY789/30OCT VTGHI BLR
STD 1825Z ATD 1835Z
DLA/32/0010 LOADING - HANDLER
SI GROUND EQUIPMENT NOT CONFIRMED CLEAR BEFORE PUSHBACK, STAND C02
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

`clips/clip2.mp4` · event Loading equipment at the hold · view Front quarter · **clip start
2026-10-30 18:00:00** · speed factor **6.0**, estimated from vehicle motion · Spark on.

### C3. What the console shows

- Evidence: **No complete event detected** — equipment already at the hold when the clip starts
  and still there when it ends.
- Supported by video: **Insufficient evidence**. The run summary shows `status: no_candidate`
  and `minutes_supported_by_video: null`, which the console labels **Cannot be determined**. No
  money figure, because none can be computed.
- No packet is built and no human decision is needed: TurnProof only signs what the camera saw.

## Earlier rehearsal values

An earlier version of `config/demo_cases.json` held other values, kept here so older runs can be
read: XY123 on clip1 with a 9-minute claim (18:45–18:54, clip start 18:38), expected 0 of 9 minutes
supported; XY456 on clip1 (19:55–20:07, clip start 19:55:30), expected 4 of 12. XY789 was planned on
clip3 (clip start 18:20, ×12), but with those settings clip3 shows a completion at 18:22:48, so
case C moved to clip2. The CLI and test cases in `scenarios/` carry their own synthetic claims and
are not the demo cases.

## If something differs on the day

- Muse Spark disagrees with the rule (rare): the outcome reads "cannot be determined ·
  operator decision required". That is the designed behaviour — the operator reviews the
  frames and uses **Correct** or **Confirm** with a note, and the packet records that a human
  decided.
- The Muse Spark keyframe check must be on: a run uploaded with it off stays at "Awaiting AI
  keyframe check" and cannot be reviewed; upload again with the check on.
- The "Loading complete" time moves by a few seconds if the cache is cold and SAM is
  re-queried (new boxes, same footage).
- A missed field in New Claim can be fixed by registering the claim again; the earlier one
  stays listed until `make reset-demo`.
