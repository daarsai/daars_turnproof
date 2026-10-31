# TurnProof — Product & System Design

Oct 31, 2026 · @DAARS · DAARS Instruments — internal working document, v0.1

## Purpose and status

This document fixes what TurnProof is for the Meta Global AI Developer Hackathon 2026 (Startup track; submission due Wed 4 Nov 2026, 9:00 PM ET = Thu 5 Nov, 07:30 IST) so a single engineer can build for four days without drifting. Design frozen 31 Oct 2026, v0.1. Code-level detail lives in the companion doc [TurnProof — Implementation Details](https://claude.ai/artifact/J1iJmLbYRUPW5WJw5Mkm4q). Any change to the table below is written here first, with a one-line reason; nothing in the build may contradict it.

| Item | Locked decision |
| --- | --- |
| Working name | TurnProof (repo `turnproof`); rename later if needed |
| Track and theme | Startup track; theme "Build for Your World" |
| One-line | Video-backed, delay-code-linked turnaround evidence packets a ground handler uses to contest airline delay attribution — upload-first, zero integration |
| Buyer | Ground handler station / service-quality team (one side; not a neutral arbiter) |
| The one event | Ramp-handling milestone reconciliation: loader docked at hold → loader departed (loading complete) → hold door closed, against the airline's claimed delay code and minutes and the handler's own log |
| Meta models | SAM 3.1 (detection, tracking, aircraft-relative zones, person masks); Muse Spark 1.3 (keyframe facts, rule override, dispute-note draft); Muse Voice Transcribe (P2 only: human statement) |
| Footage | Three licensed real apron clips (two minimum); dispute metadata is synthetic and labelled so |
| Scope rule | One event, one packet, one review screen. No lane obstruction, queues, live RTSP, A-CDM/AODB integration, dashboards, or `possible_causes` in the packet |
| Demo artifact | 3-minute video recorded Tue 3 Nov; submit by 23:00 IST Wed 4 Nov |
| Success bar | Estimated winner band ≈ 8/10 on the rubric (Impact 30, Meta tooling 25, Demo 25, Technical 20); current spec scored 6.3 by three independent review passes; the changes in this doc target the gap |

## Problem statement

Ground handlers pay SLA penalties for delay minutes they often cannot disprove, because the evidence on their side is a handwritten or handheld milestone log and an email chain, while the airline's delay code stands on its authority.

**How attribution works today.** When a flight departs late the airline assigns an IATA delay code and the minutes to the responsible party; airline–handler contracts commonly run a bonus–malus scheme that penalises the causative party ([IATA delay codes](https://en.wikipedia.org/wiki/IATA_delay_codes)). The contract template is IATA's Standard Ground Handling Agreement with an SLA attached to Annex B ([IATA](https://www.iata.org/en/publications/newsletters/iata-knowledge-hub/what-is-the-iata-standard-ground-handling-agreement-sgha-and-what-has-changed-in-the-latest-edition)). Monthly performance is computed from the registered delay codes through a delay-code validation process between the parties, with rebates when per-code delays exceed targets ([Bologna Airport SLA](https://www.bologna-airport.it/System/files/2018/TariffeAviation/SLA-2020-2023-finale-per-sito.pdf)). The handler contests same day by email with its milestone log against the airline's times; leftovers go to the monthly review and are netted off the invoice weeks later. CCTV almost never appears.

**Where the money sits.** Most contested minutes are ramp-handling codes 31–33 (loading and unloading, loading equipment) and minimum-ground-time arguments; the disputed facts are timestamps: when the loader was at the hold, when the last bag went on, when the hold door closed. Penalties are real: Toronto Pearson introduced fines for baggage handlers and Ottawa cancelled Menzies' licence for poor service ([Globe and Mail](https://theglobeandmail.com/business/article-pearson-airport-sets-fines-for-baggage-handling-companies-that-fail-to/)); in Sept 2026 PIA was fined over baggage delays and disputed responsibility ([Pakistan Observer](https://pakobserver.net/?p=778672)).

**Who already sells into this.** Assaia (Series B $26.6M, Dec 2025) converts existing CCTV into turnaround data with real-time alerts and names data-driven SLA management and delay-code clearing as targets; its customers include Swissport, Menzies and dnata at major hubs ([Assaia Ljubljana case](https://www.assaia.com/customer-stories/ljubljana-airport-reduces-ground-delays-by-4-minutes-per-flight-with-assaia)). The gap TurnProof targets is the station with no such system: no integration, no camera project, a clip and two files.

**Unvalidated (state openly, do not claim):** whether airports release footage to a handler for a commercial dispute (release is normally for safety, damage or police cases; retention is often about 30 days); which side buys first; whether delay-code reviewers accept machine-derived timestamps; whether smaller stations feel under-served rather than under-digitised.

## Solution

TurnProof turns one stand-camera clip plus two small files into a signed, hash-verified evidence packet, mapped to the IATA delay-code family, that the handler attaches to its same-day dispute email and that the airline can verify without TurnProof.

**How it works, in order**

1. Upload the clip, `clip_meta.json` (station, stand, flight, declared start time), `airline_claim.json` (code, minutes) and `handler_log.csv` (the handler's own milestone times).
2. Every original frame is hashed before anything else happens; originals are encrypted at rest; people are blurred in every frame shown.
3. SAM 3.1 finds the aircraft and derives the hold and service regions from its outline (no hand-drawn boxes), then finds and tracks the belt loader.
4. Geometry turns the loader track into milestones: docked at hold, departed (loading complete). Muse Spark reads three keyframes at each boundary and returns structured facts (door open or closed, agree or disagree with the rule), never a verdict.
5. The discrepancy table lines up video, the handler log and the airline claim per milestone, in minutes.
6. A handler operator confirms or rejects each candidate; low confidence or a Spark disagreement forces review. Corrections append, never overwrite.
7. The packet is signed and exported as JSON and PDF. The airline reviewer acknowledges or disputes it, and can run `verify_packet.py` on its own machine.

**What TurnProof is not.** Not live monitoring, not off-block prediction, not an operations dashboard, not a neutral arbitrator, and not a system that assigns fault. A human confirms every packet.

**Why this wedge survives Assaia.** Assaia sells a camera-integrated platform to hubs and the large handlers. TurnProof is upload-first with zero integration, priced for one station, mapped to the delay-code ritual the station already runs, and built around provenance (hash before redaction, chained event log, signature, independent verifier) and a two-party acknowledge/dispute step. Integrity is the trust feature; the delay-code workflow is the headline.

## Use cases

One use case is built for the hackathon; the others are named so nobody builds toward them by accident.

| ID | Use case | Actor | Built now? | Acceptance |
| --- | --- | --- | --- | --- |
| UC-1 | Contest a loading-related delay claim (code family 31–33) with video milestone evidence | Handler operator | Yes | Upload → packet exported and verified in under 60 s of pipeline time on a replayed clip |
| UC-2 | Counterparty review: airline acknowledges or disputes a packet and verifies it independently | Airline reviewer | Yes (minimal screen + verifier) | Acknowledge/Dispute recorded in the event log; `verify_packet.py` passes on an untouched packet and fails on a tampered one |
| UC-3 | Reject a false candidate and show that the rejection is recorded | Handler operator | Yes | One rejected candidate appears in the demo with its append-only record |
| UC-4 | Handler self-audit of milestone compliance across a day | Handler quality team | No | — |
| UC-5 | Airline-side challenge tooling | Airline station ops | No | — |
| UC-6 | Airport-hosted shared review record | Airport operator | No | — |
| UC-7 | Live alerts during the turnaround | Any | No, never in this product | — |

**Non-goals for this build:** lane obstruction, queue spillover, baggage-room congestion, multi-stand dashboards, RTSP ingestion, A-CDM/AODB/MVT integration, final delay-code assignment by software, fault attribution, retention policy engine, multi-tenant accounts.

## Users and roles

Two human roles and the system; the language model holds no role and cannot change any state.

| Role | Who, at a real station | What they can do | What they cannot do |
| --- | --- | --- | --- |
| Handler operator | Turnaround coordinator or station duty manager at the ground handler | Upload inputs, review candidates, confirm or reject, add a note or a voice statement, export and send the packet | Edit machine facts, hashes or timestamps; delete a record |
| Airline reviewer | Airline station manager or delay-code validator | Open a packet, acknowledge or dispute with a reason, download JSON/PDF, run the verifier | Edit the packet; see unredacted originals |
| System | TurnProof pipeline | Observe, create candidates, compute discrepancies, build and sign packets, write the event log | Confirm, send, acknowledge or dispute |
| Muse Spark (not a role) | — | Return structured observations and an agree/disagree on a rule claim | Trigger any state transition; assign a final code; assign fault |

In the demo both human roles are played from one console with a role toggle; in production they are separate logins.

## Inputs

Four files per run; the clip is real, the three metadata files are synthetic test data for the hackathon and are labelled as such in the UI and the packet.

| Input | Format | Required | Fields | Notes |
| --- | --- | --- | --- | --- |
| Clip | MP4 or MOV, H.264/H.265, ≤ 10 min | Yes | — | SAM 3.1 rejects VP9/WebM; re-encode with ffmpeg. One stand camera, fixed or handheld; zones are aircraft-relative, so camera motion is tolerated |
| `clip_meta.json` | JSON | Yes | `station`, `stand`, `flight_number`, `flight_date`, `airline`, `handler`, `camera_id`, `reference_start_utc` (optional), `fps` (optional) | Missing `reference_start_utc` → packet flagged `unsynced`; present → `declared` |
| `airline_claim.json` | JSON | Yes | `delay_code` (AHM 730 two-digit), `minutes`, `source` (e.g. `MVT (synthetic)`), `claim_window_utc` (optional) | The claim being contested |
| `handler_log.csv` | CSV | Yes | `milestone,t_utc` rows (e.g. `loading_complete,2026-10-30T18:07:00Z`) | The handler's own record; compared, never trusted over video |
| Voice statement | WAV/MP3 ≤ 60 s | No (P2) | — | Transcribed by Muse Voice Transcribe; stored as human statement, separate from machine facts |

Footage sourcing rule: only clips with an explicit licence allowing redistribution (Pexels/Pixabay-type free licence, CC-BY, CC0 or public domain), each recorded in `ATTRIBUTIONS.md` before use.

## Outputs

The evidence packet is the product; everything else exists to make it trustworthy or to show how it was made.

| Output | Format | Consumer | Contents |
| --- | --- | --- | --- |
| Evidence packet | Signed JSON (`schema_version 0.1`) | Both parties, verifier | Flight and stand, time-sync status, airline claim, handler log, video milestones with frame refs, Spark observed facts, discrepancy table, proposed claim, frame hashes (original and redacted), model and prompt versions, review decision and corrections, counterparty state, chain head, packet hash, Ed25519 signature |
| Packet PDF | PDF | Airline reviewer, monthly SLA meeting | Human-readable rendering of the packet: timeline, discrepancy table, three keyframes per milestone, hashes and signature block, QR or text of the packet hash |
| Verifier result | CLI output / console | Airline reviewer | Pass/fail per check: frame hashes, chain, packet hash, signature, schema |
| Run metrics | `run_metrics.json` | Engineer, judges | Frames processed and billed, Spark tokens, estimated USD, latency per stage, candidates, confirmed, rejected, false candidates per stand-hour, time-to-candidate, time-to-packet |
| Dispute note draft | Text in console | Handler operator | Spark-drafted same-day email body citing the packet; editable, never sent automatically |
| Redacted evidence frames | PNG | Both parties | Persons blurred; hash recorded; originals stay encrypted |

Not an output: a final delay code, a fault finding, or any unredacted frame.

## Demo clarity

The 3-minute video is the primary judging artifact; it must make one dispute, one packet and one tamper test land in the first minute and a half, then prove the thing holds up.

**The scenario (synthetic metadata on real footage)**

- Flight XY123, Bengaluru (BLR), stand D14. Airline claim: code 32 (loading/unloading), 9 minutes. Handler log: loading complete 18:07.
- Video: belt loader docked 17:58:04, departed 18:07:38, hold door closed 18:08:10 (Spark keyframe read).
- Discrepancy: 9 minutes under code 32 cannot have occurred after 18:08:10; proposed claim is code family 32, 0–1 minute supported by video, remainder disputed.
- A second candidate on another clip: the rule says "loader docked" but Spark sees the loader parked beside the hold with the door closed; `requires_operator_review` is set and the operator rejects it on camera.
- A third clip carries no reference clock and is flagged `unsynced`.

| Element | Real or synthetic | How it is labelled |
| --- | --- | --- |
| Apron footage | Real, licensed | `ATTRIBUTIONS.md`; on-screen credit at the end |
| Flight, claim, handler log | Synthetic | "synthetic test data" in the UI header and in the packet's `source` fields |
| Detections, milestones, hashes, signature | Real, produced live | Shown as produced; metrics shown on screen |
| Accuracy figures | Indicative only (2–3 clips) | Stated as "indicative, N clips" — never as production accuracy |

**What judges must see, mapped to the rubric**

| Rubric item (weight) | What must be on screen |
| --- | --- |
| Impact (30%) | The penalty clause and the 9 contested minutes in the first 20 s; who uses it (handler) and when (same-day dispute, monthly review) |
| Meta tooling (25%) | SAM 3.1 text prompt typed live, aircraft outline → zones derived, loader tracked; Spark JSON with observed facts and one visible override of a wrong rule candidate; Voice Transcribe only if working |
| Demo (25%) | Packet export, PDF, airline view, acknowledge/dispute; tamper test: verifier passes, one pixel changed, verifier fails |
| Technical (20%) | Unsynced flag, API timeout retried, run metrics (cost, latency), tests and CI badge, `docker compose up` |

**Storyline (180 s):** 0–20 the dispute · 20–50 upload and SAM zones/tracking · 50–85 milestone timeline and discrepancy table · 85–110 Spark facts, one rejection, one confirmation · 110–140 packet, airline view, tamper test · 140–165 production proof · 165–180 who we are, limitations, next step (one-station pilot).

**We will not claim:** deployed customers, production accuracy, neutrality, or that footage access is solved.

## Architecture

&#91;embedded content: architecture · 8 stages, 3 Meta models, 1 local store\]

Data flows top to bottom; the right column is every Meta Model API call, the left box is the insert-only store, and the accented box is what the handler sends and the airline verifies on its own machine.

## System design

One Python process, file-based run storage, SQLite for the append-only event log, and two external calls (SAM 3.1, Muse Spark); nothing else is shared state.

**Modules**

| Module | Responsibility | Key design choice |
| --- | --- | --- |
| `ingest` | Decode clip, extract frames, assign times, hash originals, encrypt, derive redacted display frames | Hash the original PNG bytes before redaction; redacted frame gets its own hash and a link to the original |
| `perception` | SAM 3.1 adapter: concept prompts, box-prompt tracking, person masks | Boxes carry all logic; masks are used only for overlays and blur. Concept pass finds the loader; a box-prompt pass with our own object ID tracks it |
| `zones` | Aircraft-relative regions from the aircraft box/mask | Config fractions of the fuselage box (aft hold, forward hold, under-fuselage corridor); recomputed each 10 s so camera motion does not matter |
| `events` | Milestones from zone overlap with hysteresis; candidate creation; event log | Docked = overlap ≥ τ for ≥ N consecutive sampled frames; every candidate is a chained log record |
| `reason` | Muse Spark adapter: keyframe facts, agree/disagree with rule claim, dispute-note draft | Schema-validated JSON, one retry with the validation error, no state authority |
| `evidence` | Discrepancy table, packet build, canonical hash, Ed25519 signature, JSON and PDF export | Canonical JSON (sorted keys, no whitespace); signature over the packet hash |
| `review` | FastAPI console with two roles; state transitions; corrections | Human-only transitions; corrections append |
| `verify` | Standalone `verify_packet.py` | Stdlib plus `cryptography` only, so the counterparty can run it without TurnProof |
| `store` | SQLite (runs, frames, events, packets) plus `data/runs/<run_id>/` | Event table is insert-only; no UPDATE or DELETE statements exist in the code |
| `metrics` | Per-run cost, latency, counts | Written as `run_metrics.json`; shown in the console footer |

**Data model (entities).** Run (clip, metadata, status) → Frames (index, times, hashes, encrypted ref) → Tracks (object ID, per-frame boxes) → Milestones (name, time, method, confidence, frame refs) → Candidates (milestone set, rule claim, Spark result, state) → Packet (signed snapshot of a confirmed candidate) ; EventLogRecords chain every state change and correction.

**Timing design.** Three times per frame: `t_raw` (index/fps), `t_ingest`, `t_ref` (declared `reference_start_utc` + index/fps). `time_sync.status` is `declared` (uploader asserted the start), `measured` (offset computed against a reference, not built this week) or `unsynced` (no reference; packet allowed but flagged). The UI never shows a `declared` time as measured.

**Integrity design.** SHA-256 of each original frame and of the source file before redaction; redacted derivatives hashed separately with a pointer to the original; event-log records chained (`hash = sha256(prev_hash + canonical(record))`); packet hash over canonical JSON excluding hash and signature; Ed25519 signature with a demo key pair (production: HSM or KMS). The verifier recomputes all of it from the packet plus the redacted frames and reports pass/fail per check.

**State machine (summary).** OBSERVED → CANDIDATE → UNDER\_REVIEW → CONFIRMED or REJECTED → SENT → ACKNOWLEDGED or DISPUTED → RESOLVED → ARCHIVED. Only the handler operator moves a candidate to CONFIRMED/REJECTED/SENT; only the airline reviewer moves it to ACKNOWLEDGED/DISPUTED; the system creates OBSERVED and CANDIDATE. Spark output cannot move anything. Full transition table in the implementation doc.

**Failure handling.** API calls retry three times with backoff; a final failure leaves the run `incomplete` with an `errors[]` list and blocks confirmation. Missing reference clock → `unsynced` banner. Spark confidence below 0.7 or a disagreement with the rule claim forces human review.

**Security and privacy.** Originals encrypted at rest (AES-256-GCM); persons blurred using SAM masks before any frame is displayed or exported; no unredacted frame leaves the store; secrets only in `.env`; Standard-mode models only so prompts and frames are not used for training. Workplace-monitoring posture: post-hoc, incident-scoped, persons blurred, no identity, no performance scoring of individuals.

**Metrics.** Frames processed and billed, SAM requests, Spark tokens in/out, estimated USD, latency per stage, candidates created/confirmed/rejected, false candidates per stand-hour (= rejected ÷ clip hours), time-to-candidate, time-to-packet, hash verification pass rate. Precision is reported only as "indicative, N clips".

## Prerequisites

Everything below is in hand or obtainable today; none of it requires a GPU, because perception runs through the Model API.

| Area | Requirement | Status / action |
| --- | --- | --- |
| Hackathon | Accepted participant, Startup track; Official Rules accepted; Discord access for office hours | Done (applied as startup); confirm track on the submission portal |
| Meta Model API | API key (`MODEL_API_KEY`), $150 credits claimed; Standard-mode models only (`sam-3.1`, `muse-spark-1.3`, `muse-voice-transcribe-1.0`) | Day 0: claim credits, run one SAM image call, one SAM video call, one Spark image call, one transcribe call |
| Footage | Two to three real apron clips (MP4/MOV, H.264) with a visible belt loader at a hold; licences saved | Day 0: source and record in `ATTRIBUTIONS.md` before any coding |
| Tooling | Python 3.11, ffmpeg, Docker + Compose, Git, GitHub repo (public, created after 26 Oct), GitHub Actions | Day 0: repo skeleton with CI green |
| Libraries | `openai` SDK (base URL override), `opencv-python-headless`, `numpy`, `pydantic`, `fastapi`, `uvicorn`, `jinja2`, `cryptography`, `tenacity`, `fpdf2`, `pytest`, `ruff` | Pin in `pyproject.toml` |
| Reference data | AHM 730 delay-code list (ramp handling 31–39) copied into `config/ahm730_codes.yaml` from a published list | Day 0: copy, do not type from memory |
| Hardware | Laptop; local OpenCV frame extraction only; no GPU needed | Available |
| Demo kit | Screen recorder, microphone, editor; DAARS palette (navy/orange) CSS variables for the console | Day 3 |
| People | One engineer full time for Days 1–4; a second person to review the video on Day 4 | Confirm |
| Time | ≈ 4.5 engineer-days: Sat 31 Oct (part) to Wed 4 Nov 23:00 IST | Fixed |

## Constraints and compliance

The build is governed by the hackathon's rules, our own IP hygiene, and what we are allowed to say about the company.

**Hackathon rules we must satisfy**

- Theme fit ("Build for Your World") and genuine use of the Meta Model API: both are pass/fail before scoring.
- New work only: the demo shows only what was built during the event; the repo is created after 26 Oct and nothing is imported from existing codebases.
- Public repo, team of at most four, one submission, one track (Startup), 3-minute video; submission by 9:00 PM ET on 4 Nov (07:30 IST, 5 Nov).
- Nothing shared during the event is confidential; the organisers receive a perpetual licence to use the submission. Keep anything proprietary out.

**IP hygiene**

- No code, schema, prompt or design from DAARS's existing products enters the repo. The TurnProof packet schema and event-log design are new and airport-specific.
- No internal architecture documents of other DAARS products are referenced in the repo, README or video.
- Footage only under licences that permit redistribution, each credited.

**Data handling**

- Standard-mode model IDs only (never `-contributor`), so prompts, frames and outputs are not used for training.
- No real passenger, flight or employee data; all claim and log files are synthetic and labelled.
- Persons blurred in every displayed or exported frame; originals encrypted; `.env` never committed; a secrets scan runs before submission.

**What we may say about the company**

- Allowed: deep-tech company, DPIIT-recognised, Bengaluru; founder with 15+ years in aerospace and automotive vision-AI; an AI video-analytics platform in evaluation with a transit operator; TurnProof is its aviation vertical, built this week on Meta models.
- Not allowed: "deployed", customer names, team-member names beyond the two founders, internals of other products, any claim of accuracy beyond the clips shown, any claim that footage access is solved.

## Risks and open questions

The build risks are engineering risks with known mitigations; the business risks stay open and are stated as such in the video.

| # | Risk | Impact | Mitigation | When |
| --- | --- | --- | --- | --- |
| 1 | No licensed footage shows a loader docking and leaving a hold | No milestone to demo | Source clips first, before any code; accept two clips; staged footage only as last resort and labelled | Day 0 |
| 2 | SAM mask token grammar not decoded in time | No overlays or blur | All logic on boxes; blur falls back to box-blur over person boxes; masks are cosmetic | Day 0–1 |
| 3 | Concept-prompt object IDs do not persist across frames | Broken loader track | Concept pass to locate, then box-prompt pass with our own object ID; one request per concept | Day 1 |
| 4 | Spark structured-output syntax unknown | Invalid JSON | Instruction + pydantic validation + one retry with the error; tested Day 0 | Day 0 |
| 5 | Zone fractions wrong for a clip's camera angle | False docked/undocked | Per-clip fraction override in config; hysteresis; Spark override check | Day 1–2 |
| 6 | One engineer, 4.5 days | Incomplete build | Binding cut order (see implementation doc); video recorded Tue, not Wed | All |
| 7 | API outage during recording | No live demo | Cache every API response per run; the console can replay from cache | Day 2 |
| 8 | Credit overrun | Work stops | Budget ≈ $15 of $150; cost logged per run | All |

**Open questions (business, not blocking the build)**

- [ ] Will any airport release exported CCTV to a handler for a commercial SLA dispute, and on what legal basis?
- [ ] Which side buys first at a non-hub station: handler, airline or airport?
- [ ] Will an airline delay-code validator accept a video-derived timestamp as admissible input to the monthly review?
- [ ] Do smaller stations feel under-served by incumbents, or simply under-digitised?
- [ ] What is a station's monthly malus exposure in currency, from a real contract manager?

## Glossary

| Term | Meaning |
| --- | --- |
| IATA delay code (AHM 730) | Two-digit code an airline assigns to each departure delay cause; codes 31–39 cover ramp handling (e.g. 32 loading/unloading, 33 loading equipment) |
| Bonus–malus | Contract scheme that rewards or penalises the party responsible for delays, computed from delay codes |
| SGHA | IATA Standard Ground Handling Agreement (AHM 810): main agreement, Annex A (services), Annex B (location, services, charges) |
| SLA | Service Level Agreement attached to Annex B; sets measurable targets and the penalty/rebate rules |
| Delay-code validation | The monthly process in which airline and handler/airport agree the registered codes before penalties are computed |
| MVT | IATA aircraft movement message (AHM 780) carrying actual times and delay codes; here only the synthetic claim derived from it is used |
| A-CDM | Airport Collaborative Decision Making; shared milestone and target-time framework; out of scope |
| Turnaround | Ground time between on-blocks and off-blocks during which the aircraft is serviced |
| GSE | Ground support equipment: belt loaders, high-loaders, baggage carts, tugs, fuel and catering trucks |
| Hold | Aircraft cargo compartment (forward or aft) with its own door |
| On-blocks / off-blocks | Chocks placed / removed; the standard start and end of ground time |
| Milestone | A timestamped turnaround event (loader docked, loading complete, hold door closed) |
| Evidence packet | TurnProof's signed JSON (and PDF) snapshot of a confirmed candidate with hashes, provenance and review record |
| Candidate | A machine-detected event awaiting human confirmation |
| Time-sync status | `declared` (uploader asserted start time), `measured` (offset computed), `unsynced` (no reference) |
| SAM 3.1 | Meta's Segment Anything model: text-prompted detection, segmentation and video tracking via the Model API |
| Muse Spark | Meta's multimodal reasoning model (image in, text out), used here for structured keyframe facts |
| Muse Voice Transcribe | Meta's speech-to-text model, used only for the optional human statement |
