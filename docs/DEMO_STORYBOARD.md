# TurnProof — demo video storyboard (3:00)

For the editor: the raw material is screen recordings of the console at http://127.0.0.1:8090
following `docs/DEMO_SCRIPT.md` (cases A, B, C, handler side and airline side), plus a
voice-over. Cut to the timings below; the narration lines are final. Captions are white on
navy, DAARS orange for the one number that matters in each shot. No stock music under the
narration; a low bed is fine under the opening and the closing card.

What the video has to land, in order: the problem is money nobody can prove (0:00–0:20);
the AI reads and sees but never decides (0:20–1:30); the evidence is signed and verifiable by
the other side (1:30–2:10); the same tool rules against the handler when the camera says so,
which is why both sides can adopt it (2:10–2:45); the ask (2:45–3:00).

| Time | Recording (what is on screen) | Narration (voice-over) | Caption / overlay |
|---|---|---|---|
| 0:00–0:08 | Title card, DAARS navy, TurnProof wordmark. | "Every delay minute coded against a ground handler costs money — in Europe, typically tens of euros a minute under the handling contract." | TurnProof · Aircraft Turnaround Evidence & Resolution |
| 0:08–0:20 | Airport & Cameras: the day's flights, XY123 on D14, camera registered. Hover the stand camera; snapshot. | "The airline has a telex. The handler has a hand-written log. Nobody has evidence. TurnProof turns the stand camera into a witness both sides can check." | Stand D14 · camera stand-d14-01 |
| 0:20–0:40 | Claims › New Claim. Paste the XY123 DLA message. Click Extract with Muse Spark. Fields fill in; the telex parser line says "agrees". | "The airline's message goes in as it arrived. Muse Spark reads it into a claim — flight, delay code 32, nine minutes, the claimed window. A deterministic parser cross-checks it, and the operator confirms. The AI never decides." | Muse Spark 1.3 · claim intake |
| 0:40–0:55 | Upload Footage: drop clip1.mp4, claim XY123 preselected, clip start 18:38 UTC, speed ×6. Upload and analyze. Processing page: ingest → SAM 3.1 → redact → rule → Spark → packet. | "Then the footage. Every frame is hashed, persons are blurred, and SAM 3.1 segments the aircraft and the ground equipment — no training, one noun at a time." | SAM 3.1 · aircraft · vehicle · person |
| 0:55–1:20 | Evidence Review for XY123. Step through the frame viewer: equipment at the hold, then the departure frame with the zone tint; the active-now pills change. Scroll to the Turnaround Timeline: aircraft lane, loading lane ending 18:41:30, claim window to the right, ground-staff lane. | "A rule — not a model — finds the moment the loading equipment leaves the hold: 18:41:30. The turnaround profile shows it against the flight's clock: on blocks, loading, the staff around the aircraft, and the airline's claimed window, which starts three and a half minutes after loading ended." | 18:41:30 · loading complete |
| 1:20–1:30 | Claim vs Evidence card: 9 claimed, 0 supported, outcome box "Claim not supported by video · EUR 360 not supported". | "Nine minutes claimed, zero supported. Three hundred and sixty euros that were not the handler's." | EUR 360 not supported |
| 1:30–1:45 | Record the operator statement (voice): Muse Voice Transcribe fills the text. Confirm with a note. Send to airline. Sent Packets shows the signed delivery. | "The operator states what happened — spoken, transcribed by Muse Voice. Confirm, and the packet is signed: every frame hash, every model output, every decision in a hash-chained log." | Muse Voice Transcribe 1.0 · Ed25519 signature |
| 1:45–2:10 | Switch to Airline. Received Cases: XY123 "Not supported · Sent to airline". Open, click Verify — seven checks pass. Click Tamper test — one pixel flipped, verification fails. Acknowledge with a note "Claim withdrawn". | "The airline verifies it with nothing but the public key — seven checks. Change a single pixel and it fails. They acknowledge; the claim is withdrawn, and that answer is signed into the packet too." | 7 of 7 checks pass · tamper → FAIL |
| 2:10–2:35 | Case B, already analysed: Evidence Review for XY456. Timeline shows loading ending 19:59, four minutes into the window. Outcome box "Claim partly supported · 4 of 12 min · EUR 160 supported, EUR 320 not". Handler-log row: log said 19:58, video 19:59. | "Same tool, other outcome. On XY456 loading really ran four minutes past scheduled departure. Four minutes stand, eight do not — and the handler's own log was a minute optimistic. Evidence cuts both ways. That is why an airline can accept it." | 4 of 12 min stand |
| 2:35–2:45 | Case C: Evidence Review for XY789, "No complete event detected", outcome "Cannot be determined". | "And when the camera does not show the end, TurnProof says so. It never invents a minute." | Cannot be determined |
| 2:45–3:00 | Overview with the three cases in the work queue; then the closing card. | "TurnProof, by DAARS Instruments: built on SAM 3.1, Muse Spark and Muse Voice Transcribe, with a signed evidence packet anyone can verify. Next: live stand cameras and the airline's AODB feed, which the station page already reads." | DAARS Instruments · TurnProof v0.1 · github.com/daarsai/daars_turnproof |

Recording notes

- Record at 1440×900 or larger, browser zoom 100 %, handler and airline in two separate
  recordings so the role switch is a clean cut. Hide the bookmarks bar.
- Record case A end to end first (claim, upload, review, send, airline verify, tamper,
  acknowledge). Record B and C only at the result screens; they can be prepared with
  `python scripts/run_demo_cases.py --cases B,C` before recording.
- For the voice statement, use the actual microphone on the Evidence Review page; keep the
  transcription on screen for a second so the text is readable.
- The Tamper test writes a modified copy; it never touches the signed packet. Show the FAIL
  line in red.
- Leave the "Demo data" badge visible; do not crop it. Every number in the video is synthetic
  test data on licensed footage, and the closing card says so in one line.
- The one thing not to say: that the system decides. Models detect and flag; people decide.
