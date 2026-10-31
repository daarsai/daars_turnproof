# TurnProof — Implementation Details

Oct 31, 2026 · @DAARS · DAARS Instruments — internal working document, v0.1

## Scope of this document

This is the build contract for TurnProof: the exact Model API calls, schemas, algorithms, state machine, repo layout, day plan and video script a single engineer follows from Sat 31 Oct to submission on Wed 4 Nov 2026. Product intent, use cases and constraints are in [TurnProof — Product & System Design](https://claude.ai/artifact/5UtV6wAbMW7Aub7guUA2cY); where the two disagree, the design doc's locked-decisions table wins and this document is corrected. Everything here is new work for the hackathon; nothing is carried over from other DAARS codebases.

## Meta Model API interface

All three models are reached through one base URL with the OpenAI SDK; SAM 3.1 and Muse Spark go through the Responses API, Voice Transcribe through its own ASR endpoint. Facts below come from Meta's developer docs as read on 31 Oct 2026 ([overview](https://dev.meta.ai/docs/overview), [segmenting with prompts](https://dev.meta.ai/docs/sam/segmenting), [media segmentation](https://dev.meta.ai/docs/media-segmentation), [LiteLLM provider page](https://docs.litellm.ai/docs/providers/meta)); anything marked *undocumented* is confirmed on Day 0 by a test call, never assumed.

**Connection**

- Base URL `https://api.meta.ai/v1`; Bearer token from `MODEL_API_KEY`; drop-in compatible with the OpenAI SDK (`OpenAI(base_url=..., api_key=...)`).
- Standard-mode model IDs only: `sam-3.1`, `muse-spark-1.3`, `muse-voice-transcribe-1.0`. Never a `-contributor` ID.
- Pricing used for budgeting: Muse Spark $1.25 per M input and $4.25 per M output tokens; SAM 3.1 $2.50 per 1,000 images and $0.20 per 1,000 video frames (50-frame minimum per request); Voice Transcribe $0.18 per hour. $150 credits per participant; planned spend under $15.

**SAM 3.1 — request**

| Element | How |
| --- | --- |
| Endpoint | `POST /v1/responses`, `model: "sam-3.1"`, or `client.responses.stream(...)` with `stream=True`, `Accept: text/event-stream` |
| Message | One `user` message; `content` = one `input_text` part plus one `input_image` (`image_url`: public URL or base64 data URL) or one `input_video` (`video_url`, or `file_id` from `POST /v1/files` with `purpose: user_data`) |
| Concept prompt | `input_text.text` = one short noun phrase ("aircraft", "belt loader", "person"). One concept per request; several concepts = several requests |
| Box/point prompt | Tokens inside `input_text`: frame marker `<Nf>`, box `<\|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..\|>`, point `<\|point;x=..;y=..;w=..;h=..\|>` (leading `-` = negative point); Python helper `build_object_prompt`. Never mix a concept phrase and tokens in one request |
| Metadata | `metadata.propagation_direction` = `both` (default), `forward`, `backward`; `include_confidence` = `"true"`/`"false"` (string); `mask_encoding` = `lossless` (default) or `one_bit` |
| Video limits | MP4 or MOV, H.264/H.265/MPEG-4 (VP9/WebM rejected); up to 15,000 frames (\~10 min) per request; up to 16 objects per frame and 16 prompted objects; late-index MP4s are remuxed on upload |
| Undocumented | fps or frame-sampling option; max file size and resolution; whether concept-prompt object IDs persist across frames; exact mask token grammar (see "Reading segmentation output" in the docs) |

**SAM 3.1 — response.** Streamed `response.output_text.delta` events until `response.completed`; the text is one record per object per frame: frame marker `<Nf>`, object ordinal, a box token (inclusive `x1,y1,x2,y2` plus source `w,h`), and a mask token (`~` lossless, `!` one-bit). Confidence `c` (0–1) appears only with `include_confidence: "true"`. Concept results arrive in ascending frame order; box/point-prompted results may arrive out of order, so key everything by frame marker. Prompted objects report under the IDs you assign.

**SAM 3.1 — our strategy**

1. Decode boxes first; all milestone logic runs on boxes. Masks are decoded only for overlays and person blur, and if the grammar is not decoded by Day 1 evening, blur falls back to a box blur over `person` boxes.
2. Three concept passes per clip: `aircraft` (every 10 s, for zones), `person` (all frames, for blur), `belt loader` (first 10 s, to locate). Then one box-prompt pass on the full clip with our own object ID for the loader so the track is stable; `propagation_direction: forward`.
3. Cache every raw response under `data/runs/<run_id>/api/` so the console and the video can replay without the API.

**Muse Spark** (`muse-spark-1.3`): accepts text, image, video and PDF input and returns text; supports structured outputs, function calling, parallel tool calls and prompt caching; `reasoning_effort` ∈ `minimal`, `low`, `medium`, `high`, `xhigh` (use `medium`). The exact structured-output parameter is *undocumented* in the pages read: Day 0 tests the OpenAI-style `json_schema` response format; fallback is a "JSON only" instruction, pydantic validation, and one retry that feeds back the validation error. Three keyframes go in as base64 image parts; the structured context (detections, zones, milestone candidates, claim) goes in as text.

**Muse Voice Transcribe** (`muse-voice-transcribe-1.0`): file endpoint `POST /v1/asr/transcribe`, realtime `wss://api.meta.ai/v1/asr/realtime`; turn-level timestamps, optional speaker labels, 25 languages. Supported file formats are *undocumented*; the Day 0 test sends a 16 kHz mono WAV. P2 feature: if the test fails in under two hours, the voice feature is dropped entirely (no non-Meta speech model).

## Repository layout and stack

One Python package, one FastAPI app, one standalone verifier; the repo is public and is created fresh after 26 Oct.

```text
turnproof/
  README.md                 what/why, architecture (Mermaid), quickstart, metrics, limitations
  LICENSE                   Apache-2.0
  ATTRIBUTIONS.md           footage sources and licences
  SECURITY.md               key handling, redaction, what is and is not encrypted
  docs/SPEC.md              export of the two design docs
  docs/VIDEO_SCRIPT.md      the 180 s script
  config/config.yaml        zone fractions, thresholds, fps, model IDs
  config/ahm730_codes.yaml  ramp-handling delay codes 31–39 (copied from a published AHM 730 list)
  .env.example              MODEL_API_KEY=, TURNPROOF_DATA_KEY=, TURNPROOF_SIGNING_KEY=
  turnproof/
    cli.py                  run, review-serve, export, verify, metrics
    ingest/                 decode.py, frames.py, hashing.py, crypto.py, redact.py
    perception/             sam_client.py, sam_parse.py, tracks.py
    zones/                  aircraft_zones.py
    events/                 milestones.py, candidates.py, eventlog.py
    reason/                 spark_client.py, prompts.py, schemas.py
    evidence/               discrepancy.py, packet.py, canonical.py, sign.py, pdf.py
    review/                 app.py (FastAPI), templates/, static/, state_machine.py
    store/                  db.py (SQLite), paths.py
    metrics/                collector.py
  verify_packet.py          stdlib + cryptography only
  clips/                    gitignored; the three demo clips
  fixtures/                 3 frames + recorded SAM/Spark responses for offline tests
  tests/                    test_hashchain.py test_state_machine.py test_schema.py
                            test_verifier.py test_zones.py test_pipeline_replay.py
  .github/workflows/ci.yml  ruff + pytest, no API keys
  Dockerfile  docker-compose.yml  Makefile  pyproject.toml
```

| Layer | Choice | Why |
| --- | --- | --- |
| Language | Python 3.11 | Speed of build; OpenCV and the OpenAI SDK are mature |
| API client | `openai` SDK with `base_url=https://api.meta.ai/v1` | Documented drop-in path for Responses API |
| Video | `ffmpeg` (re-encode, remux) + `opencv-python-headless` (frames) | Deterministic PNG frames for hashing |
| Models/validation | `pydantic` v2 | Strict Spark output schema, packet schema |
| Web | `fastapi`, `uvicorn`, `jinja2`, vanilla JS, CSS variables in DAARS navy/orange | Two screens, no build step |
| Crypto | `cryptography` (AES-256-GCM, Ed25519, SHA-256 via `hashlib`) | Standard primitives; same lib in the verifier |
| Retry | `tenacity` | Three attempts with exponential backoff on API calls |
| PDF | `fpdf2` | Pure Python, no system deps |
| Storage | SQLite via `sqlite3` | Insert-only event table; zero ops |
| Tests/CI | `pytest`, `ruff`, GitHub Actions | Offline replay fixtures so CI needs no key |
| Deploy | Docker + Compose, Makefile | `docker compose up` in the video |

## Configuration

All tunables live in `config/config.yaml`; secrets live only in `.env`; the delay-code list is data, not code.

```yaml
# config/config.yaml (v0.1 defaults; per-clip overrides under clips.<name>)
models:
  sam: sam-3.1
  spark: muse-spark-1.3
  asr: muse-voice-transcribe-1.0
  spark_reasoning_effort: medium
sampling:
  logic_fps: 2            # local rule evaluation rate
  aircraft_every_s: 10    # zone recomputation interval
  loader_locate_window_s: 10
zones:                     # fractions of the aircraft box; x along fuselage, y down
  aft_hold:     {x0: 0.62, x1: 0.95, y0: 0.45, y1: 0.95, pad_out: 0.35}
  forward_hold: {x0: 0.08, x1: 0.40, y0: 0.45, y1: 0.95, pad_out: 0.35}
  corridor:     {x0: 0.00, x1: 1.00, y0: 0.70, y1: 1.30}
rules:
  docked_overlap_tau: 0.30   # loader box ∩ hold region / loader box area
  docked_min_frames: 6       # at logic_fps=2 → 3 s hysteresis
  undocked_min_frames: 6
  spark_confidence_floor: 0.70
integrity:
  hash_alg: sha256
  signature_alg: ed25519
  key_id: turnproof-demo-2026
clips:
  clip1: {reference_start_utc: "2026-10-30T17:55:00Z", zones: {aft_hold: {x0: 0.60}}}
  clip3: {reference_start_utc: null}   # demonstrates unsynced
```

- `config/ahm730_codes.yaml`: `code: {family, title}` for 31–39, copied from a published AHM 730 list on Day 0 and cited in the file header. Do not type codes from memory.
- `.env`: `MODEL_API_KEY` (Meta), `TURNPROOF_DATA_KEY` (32-byte base64 for AES-GCM), `TURNPROOF_SIGNING_KEY` (Ed25519 private key, PEM). `.env.example` ships with empty values; a pre-commit secrets scan blocks accidental commits.
- Zone fractions are heuristic v0 calibrated by eye on clip 1 (Day 0) and overridden per clip; the packet records the fractions used under `models.zones_config_sha256`.

## Data schemas

Four input files, one packet schema, one Spark output schema and one event-log record; all are pydantic models in `turnproof/reason/schemas.py` and `turnproof/evidence/packet.py`, and the packet schema is versioned from day one.

**Input files**

```json
// clip_meta.json
{"station":"BLR","stand":"D14","flight_number":"XY123","flight_date":"2026-10-30",
 "airline":"XY Airways","handler":"Handler Co","camera_id":"stand-d14-01",
 "reference_start_utc":"2026-10-30T17:55:00Z","fps":25.0,"data_label":"synthetic test data"}

// airline_claim.json
{"delay_code":"32","minutes":9,"source":"MVT (synthetic test data)",
 "claim_window_utc":{"start":"2026-10-30T18:05:00Z","end":"2026-10-30T18:14:00Z"}}
```

```csv
milestone,t_utc
loader_docked_start,2026-10-30T17:58:00Z
loading_complete,2026-10-30T18:07:00Z
hold_door_closed,2026-10-30T18:08:00Z
```

**Evidence packet (`schema_version: "0.1"`)**

```json
{
  "packet_id": "TP-20261102-0001", "schema_version": "0.1", "created_at_utc": "...",
  "station": "BLR", "stand": "D14",
  "flight": {"number": "XY123", "date": "2026-10-30", "airline": "XY Airways", "registration": null},
  "parties": {"handler": "Handler Co", "airline": "XY Airways"},
  "data_label": "synthetic test data on licensed footage",
  "source": {"type": "upload", "camera_id": "stand-d14-01", "file_sha256": "...", "fps": 25.0, "duration_s": 62.4},
  "time_sync": {"status": "declared", "reference_start_utc": "...", "measured_offset_s": null, "method": "uploader_declared"},
  "airline_claim": {"delay_code": "32", "minutes": 9, "source": "MVT (synthetic test data)"},
  "handler_log": [{"milestone": "loading_complete", "t_utc": "..."}],
  "milestones": [
    {"name": "loader_docked_start", "t_utc": "...", "frame_index": 1251, "method": "sam31_box_overlap", "zone": "aft_hold", "confidence": 0.91, "evidence_frames": ["f1251", "f1255", "f1260"]},
    {"name": "loading_complete", "t_utc": "...", "frame_index": 2437, "method": "sam31_box_overlap", "zone": "aft_hold", "confidence": 0.88, "evidence_frames": ["..."]},
    {"name": "hold_door_closed", "t_utc": "...", "frame_index": 2452, "method": "spark_keyframe", "zone": "aft_hold", "confidence": 0.74, "evidence_frames": ["..."]}
  ],
  "observed_facts": [{"text": "Belt loader is clear of the aft hold; hold door closed.", "frames": ["f2452"], "source": "muse-spark-1.3"}],
  "discrepancies": [{"milestone": "loading_complete", "video_utc": "...", "handler_log_utc": "...", "airline_claim_minutes": 9, "video_supported_minutes": 0, "delta_min": 9}],
  "proposed_claim": {"delay_code_family": "32", "minutes_supported_by_video": 0, "basis": "loading_complete precedes the claimed window"},
  "evidence_frames": [{"id": "f2437", "t_utc": "...", "frame_index": 2437, "sha256_original": "...", "sha256_redacted": "...", "redaction": "persons_blurred_sam31", "original_ref": "enc/f2437.bin"}],
  "models": {"sam": {"id": "sam-3.1", "prompts": ["aircraft", "belt loader", "person"]}, "spark": {"id": "muse-spark-1.3", "prompt_sha256": "...", "reasoning_effort": "medium"}, "asr": null, "zones_config_sha256": "..."},
  "human_statement": null,
  "review": {"decision": "confirmed", "operator": "handler-ops-01", "t_utc": "...", "note": "...", "corrections": [{"seq": 1, "field": "...", "old": "...", "new": "...", "t_utc": "..."}]},
  "counterparty": {"state": "PENDING", "actor": null, "t_utc": null, "reason": null},
  "chain": {"event_log_head_sha256": "...", "prev_packet_sha256": null},
  "packet_sha256": "...",
  "signature": {"alg": "Ed25519", "key_id": "turnproof-demo-2026", "sig_base64": "..."}
}
```

Rules: `packet_sha256` = SHA-256 of canonical JSON (sorted keys, no whitespace, UTF-8) excluding `packet_sha256` and `signature`; the signature is over `packet_sha256`. There is no `possible_causes` field and no unredacted frame reference other than the encrypted `original_ref`.

**Spark output schema (strict; extra keys rejected)**

```json
{"observed_facts": [{"text": "string", "frames": ["f2452"]}],
 "hold_door_state": "open | closed | unknown",
 "rule_claim_check": {"claim": "loader_docked | loader_departed", "agree": true, "reason": "string"},
 "candidate_delay_code_family": "31|32|33|34|35|36|37|38|39|none",
 "confidence": 0.0,
 "requires_operator_review": true}
```

**Event-log record (append-only)**

```json
{"seq": 17, "t_utc": "...", "run_id": "...", "actor": "system | handler_operator | airline_reviewer",
 "action": "candidate_created | review_confirmed | correction | packet_sent | acknowledged | disputed",
 "from_state": "CANDIDATE", "to_state": "UNDER_REVIEW", "payload_sha256": "...",
 "prev_hash": "...", "hash": "sha256(prev_hash + canonical(record without hash))"}
```

## Pipeline stage specifications

Eight stages run in order per clip; each writes to `data/runs/<run_id>/` and appends to the event log, and every stage can be re-run from the cached API responses.

**1. Ingest (`turnproof/ingest`)**

- Re-encode with `ffmpeg -c:v libx264 -movflags +faststart` if the container or codec is not SAM-accepted; record the source file SHA-256 before and after.
- Extract every frame with OpenCV; encode each as PNG with fixed compression level so bytes are deterministic; `sha256_original` = SHA-256 of those bytes.
- Times: `t_raw = idx / fps`; `t_ingest = now()`; `t_ref = reference_start_utc + t_raw` when declared, else null and `time_sync.status = unsynced`.
- Encrypt each original PNG with AES-256-GCM (`TURNPROOF_DATA_KEY`, random 96-bit nonce, frame id as associated data) to `enc/f<idx>.bin`; keep no plaintext originals after redaction completes.
- Redaction: after the `person` SAM pass, blur the mask (or the box when the mask grammar is not decoded) with a Gaussian kernel sized 1/8 of the box height; write `display/f<idx>.png` and `sha256_redacted`.

**2. Perception (`turnproof/perception`)**

- `sam_client.segment(prompt, image|video, metadata)` streams the response and stores the raw text under `api/sam/<call_id>.txt`.
- `sam_parse` extracts per-frame records: `(frame_idx, object_id_or_ordinal, x1, y1, x2, y2, c, mask_token)`; boxes are converted to the frame's pixel space using the returned `w,h`.
- Loader track: concept pass `"belt loader"` on the first 10 s; pick the highest-confidence box; box-prompt pass on the full clip with frame marker `<0f>`, our object ID 1, `propagation_direction: forward`; the result is `tracks/loader.json` (one box per frame, gaps allowed).
- Second GSE class (`baggage cart`) only if time allows; it is not required for the demo.

**3. Zones (`turnproof/zones`)**

- Aircraft box from the `aircraft` concept pass every 10 s (interpolated between samples).
- Fuselage axis: the long side of the aircraft box; `x` runs nose→tail along it, `y` top→bottom. Regions are fractions of that box from `config.zones`, extended outward below the fuselage by `pad_out × box height` so a loader standing beside the hold falls inside the region.
- Output: `zones/<t>.json` polygons in pixel space for `aft_hold`, `forward_hold`, `corridor`; redrawn on every overlay frame.

**4. Events (`turnproof/events`)**

- Sample the loader track at `logic_fps`; `overlap = area(loader_box ∩ hold_region) / area(loader_box)`.
- Docked state machine with hysteresis: `UNDOCKED → DOCKED` after `docked_min_frames` consecutive frames with `overlap ≥ tau`; `DOCKED → UNDOCKED` after `undocked_min_frames` consecutive frames with `overlap < tau`.
- Milestones: `loader_docked_start` = first frame of the DOCKED run; `loading_complete` = first frame of the following UNDOCKED run; confidence = mean `c` over the run's frames.
- A candidate is created when a `loading_complete` milestone exists; it carries the three milestones, their evidence frames (first, middle, last frame of each run, plus one frame 5 s after `loading_complete` for the door check) and the rule claim.
- Every candidate creation appends an event-log record.

**5. Reason (`turnproof/reason`)**

- Input to Spark: three redacted keyframes (base64) and a text block with: the rule claim, milestone times, zone names, loader boxes per keyframe, the airline claim, the handler log, and the schema.
- System text rules: observations only; cite frame ids; `hold_door_state` from the post-complete frame; `agree=false` when the images contradict the claim; `candidate_delay_code_family` from the AHM 730 list or `none`; never assign responsibility; JSON only.
- Validation: pydantic strict; on failure one retry with the validation error appended; on second failure the candidate is marked `requires_operator_review=true` with `spark_status: failed`.
- Second Spark call (P1): draft the same-day dispute email body from the packet fields; displayed, editable, never sent.

**6. Evidence (`turnproof/evidence`)**

- Discrepancy per milestone: `video_utc` vs `handler_log_utc` vs the airline claim window; `video_supported_minutes` = minutes of the claim window that fall before `loading_complete` (clamped at 0); `delta_min` = claimed − supported.
- Build the packet (schema above), compute `packet_sha256` over canonical JSON, sign with Ed25519, write `packets/<packet_id>.json`, render `packets/<packet_id>.pdf` with `fpdf2` (timeline, discrepancy table, 3 keyframes per milestone, hashes, signature block).

**7. Review (`turnproof/review`)**

- FastAPI app; state transitions only through `state_machine.transition(actor, action)`; every transition writes an event-log record; corrections are new records, never edits.
- Role toggle (handler / airline) in the demo; separate logins are out of scope.

**8. Verify (`verify_packet.py`)**

1. Load packet JSON; validate schema version `0.1`.
2. Recompute `sha256_redacted` for every frame in `display/` and compare.
3. Recompute the event-log chain from the exported `eventlog.jsonl` and compare `chain.event_log_head_sha256`.
4. Recompute `packet_sha256` from canonical JSON; verify the Ed25519 signature with the public key shipped beside the packet (`keys/turnproof-demo-2026.pub`).
5. Print one line per check: `PASS`/`FAIL`; exit code 0 only if all pass. Changing one pixel of any display frame must produce a `FAIL`.

## State machine

&#91;embedded content: candidate state machine · 10 states, 3 actors\]

The system creates and completes candidates, the handler operator decides and sends, the airline reviewer answers, and Muse Spark can only raise the review flag.

| From | Action | Actor | Guard | To |
| --- | --- | --- | --- | --- |
| OBSERVED | milestones detected | system | `loading_complete` milestone exists | CANDIDATE |
| CANDIDATE | spark evaluated | system | Spark result stored, or `spark_status: failed` | UNDER\_REVIEW |
| UNDER\_REVIEW | confirm | handler\_operator | Human action required; blocked while `requires_operator_review` is unanswered or `confidence < 0.70` without an explicit override note | CONFIRMED |
| UNDER\_REVIEW | reject | handler\_operator | Reason note required | REJECTED |
| UNDER\_REVIEW | correct | handler\_operator | Appends a correction record; state unchanged | UNDER\_REVIEW |
| CONFIRMED | send | handler\_operator | Packet built, hashed and signed; verifier self-check passes | SENT |
| SENT | acknowledge | airline\_reviewer | — | ACKNOWLEDGED |
| SENT | dispute | airline\_reviewer | Reason required | DISPUTED |
| ACKNOWLEDGED / DISPUTED | resolve | either party | Resolution note | RESOLVED |
| RESOLVED / REJECTED | archive | system | Retention window elapsed (demo: manual button) | ARCHIVED |

Forbidden by construction: any transition triggered by model output; any transition without an event-log record; any edit of a past record (`UPDATE`/`DELETE` do not exist in the code).

## Integrity and cryptography

Every integrity claim in the video must be reproducible by the verifier from the packet, the display frames and the exported event log alone.

| Element | Specification |
| --- | --- |
| Canonical JSON | `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`; floats written with `repr`; timestamps ISO-8601 UTC with `Z` |
| Frame hash | SHA-256 of the deterministic PNG bytes of the original frame (`sha256_original`), computed before redaction; SHA-256 of the redacted PNG (`sha256_redacted`) |
| Source hash | SHA-256 of the clip file as uploaded; if re-encoded, both hashes recorded with the ffmpeg command line |
| Event-log chain | `hash_i = SHA-256(hash_{i-1} ∥ canonical(record_i without hash))`; genesis `hash_0 = SHA-256(run_id)`; exported as `eventlog.jsonl` |
| Packet hash | SHA-256 of canonical JSON with `packet_sha256` and `signature` removed |
| Signature | Ed25519 over the 32-byte packet hash; `key_id` names the public key file shipped beside the packet; demo key pair generated on Day 2 and committed as public key only |
| Encryption at rest | AES-256-GCM, 96-bit random nonce per frame, associated data = frame id; key from `TURNPROOF_DATA_KEY`; ciphertext file = nonce ∥ ciphertext ∥ tag |
| Redaction | Person regions blurred before any display or export; the verifier never needs originals |
| Time integrity | `time_sync.status` and `reference_start_utc` are inside the signed packet, so a later claim of a different clock is detectable |

**Verifier algorithm (`verify_packet.py packet.json --frames display/ --log eventlog.jsonl --pub keys/turnproof-demo-2026.pub`)**

1. Parse and schema-check the packet (`schema_version 0.1`).
2. For each `evidence_frames[]` entry, hash `display/<id>.png` and compare to `sha256_redacted`.
3. Rebuild the chain from `eventlog.jsonl`; compare the head to `chain.event_log_head_sha256`.
4. Strip `packet_sha256` and `signature`, canonicalise, hash, compare.
5. Verify the Ed25519 signature over the hash with the public key.
6. Print `PASS`/`FAIL` per step and a one-line summary; exit 0 only on all pass.

**Tamper test for the video:** run the verifier (all PASS); open one display frame in an editor and change one pixel; run again → step 2 `FAIL`, exit code 1. Also show that editing a milestone time in the JSON fails step 4.

**Production notes (not built this week, stated in SECURITY.md):** keys in a KMS/HSM; per-tenant signing keys; retention policy enforced by a job; key rotation with `key_id`; originals never leave the handler's premises.

## Review console

Two screens, one role toggle, DAARS palette (navy primary, orange accent, plain sans-serif), no build step.

| Route | Role | Purpose | Elements |
| --- | --- | --- | --- |
| `GET /` | both | Run list | Table of runs: clip, flight, status, candidates, metrics footer |
| `POST /runs` | handler | Upload | Four-file upload form; starts the pipeline; progress by stage |
| `GET /runs/{run_id}` | handler | Run view | Redacted video with box and zone overlays; milestone timeline; discrepancy table (video / handler log / airline claim); Spark facts panel with agree/disagree badge; candidate list with Confirm / Reject (+ required note) and Correct; `unsynced` red banner when applicable |
| `POST /candidates/{id}/transition` | handler, airline | State change | Body: `action`, `note`; enforced by `state_machine.transition` |
| `GET /packets/{packet_id}` | airline (toggle) | Packet view | Packet summary, three keyframes per milestone, hashes and signature block, Download JSON / PDF, Acknowledge / Dispute (+ reason), **Verify** button that runs the same verifier and prints the per-step result |
| `GET /verify` | both | Standalone verify | Upload a packet + frames zip → verifier output |
| `GET /metrics/{run_id}` | both | Metrics | Renders `run_metrics.json` |
| `POST /statements` (P2) | handler | Voice statement | Uploads audio → Voice Transcribe → `human_statement` attached to the candidate |

UI rules: the data label "synthetic test data on licensed footage" is visible in the header of every run; a `declared` time is shown with a "declared by uploader" tag; machine facts and human statements are in visibly separate panels; the Confirm button is disabled while `requires_operator_review` is unanswered.

## Metrics, failure handling and logging

Every run writes `run_metrics.json`; every failure path is visible in the UI and at least one appears in the video.

**`run_metrics.json`**

| Field | Definition |
| --- | --- |
| `frames_processed` | Frames extracted locally |
| `sam_requests`, `sam_frames_billed` | Requests and billed frames (50-frame minimum per request applied) |
| `spark_calls`, `spark_tokens_in`, `spark_tokens_out` | From response usage |
| `est_cost_usd` | `sam_frames_billed × 0.0002 + sam_images × 0.0025 + tokens_in × 1.25e-6 + tokens_out × 4.25e-6` |
| `latency_s` | Per stage: ingest, sam, zones, events, spark, evidence, total |
| `candidates`, `confirmed`, `rejected` | Counts |
| `false_candidates_per_stand_hour` | `rejected ÷ (clip_duration_s / 3600)` |
| `time_to_candidate_s`, `time_to_packet_s` | Pipeline time from clip start to candidate / to signed packet |
| `hash_verification` | `pass` / `fail` from the self-check after export |
| `clips_evaluated` | Count; precision is reported in the README only as "indicative, N clips" |

**Failure handling**

| Failure | Behaviour | Shown in video? |
| --- | --- | --- |
| SAM or Spark timeout / 5xx | `tenacity` retry ×3, exponential backoff 2–8 s; on final failure the run ends `incomplete` with `errors[]`; confirmation blocked | Yes (one forced timeout via a fault flag) |
| Spark invalid JSON | One retry with the validation error appended; then `spark_status: failed`, `requires_operator_review: true` | Optional |
| No `reference_start_utc` | `time_sync.status: unsynced`; red banner; packet allowed, flagged | Yes (clip 3) |
| Spark confidence < 0.70 or `agree: false` | Confirm disabled until operator writes an override note | Yes (the rejected candidate) |
| Loader never found | Run completes with `no_candidate`; no packet | No |
| Unsupported codec | ffmpeg re-encode; both hashes recorded | No |
| Credit exhaustion | Hard stop with a clear error; replay from cache still works | No |

**Logging:** structured JSON lines per stage to `data/runs/<run_id>/log.jsonl` (stage, t, duration, api call id, cost); no frame bytes or secrets in logs; every API response cached verbatim for replay.

## Testing and CI

CI runs with no API key: every model call is replayed from recorded fixtures, so a green badge is reproducible by any judge who clones the repo.

| Test file | What it proves | Fixture |
| --- | --- | --- |
| `test_hashchain.py` | Chain rebuilds to the same head; one altered record changes the head; genesis is `SHA-256(run_id)` | Ten synthetic records |
| `test_state_machine.py` | Every allowed transition succeeds with the right actor; every forbidden one raises; Spark payload cannot transition; corrections append | None |
| `test_schema.py` | Packet and Spark schemas accept the golden samples and reject unknown keys, missing fields, `possible_causes`, and a final delay code in Spark output | `fixtures/golden_packet.json`, `fixtures/spark_good.json`, `fixtures/spark_bad_*.json` |
| `test_verifier.py` | Verifier passes on the golden packet + frames; fails when one pixel changes; fails when a milestone time is edited; exit codes correct | 3 PNG frames, golden packet, public key |
| `test_zones.py` | Region polygons from an aircraft box follow the config fractions; overlap ratio is correct on hand-computed boxes | Hand-made boxes |
| `test_pipeline_replay.py` | Full pipeline on the recorded SAM/Spark responses yields the expected milestones, candidate and packet hash | `fixtures/api/*.txt`, `fixtures/api/*.json` |
| `test_sam_parse.py` | Parser reads frame markers, ordinals, box tokens and confidence from recorded output; handles out-of-order frames | Recorded SAM text |

- `ruff check` and `ruff format --check` run first; `pytest -q` second; both on Python 3.11 in `.github/workflows/ci.yml` on every push and PR.
- Fixtures are recorded on Day 1–2 from real API calls and committed (small: three frames, a few KB of text).
- A `make smoke` target runs the live pipeline on clip 1 with the real API; it is not part of CI.

## Deployment

One container, one command, and a Makefile that names every step used in the video.

```text
Dockerfile          python:3.11-slim + ffmpeg + libgl1; pip install .; CMD uvicorn turnproof.review.app:app --host 0.0.0.0 --port 8080
docker-compose.yml  service app: build ., ports 8080:8080, env_file .env, volumes ./data:/app/data ./clips:/app/clips
```

```text
make setup        create venv, install, generate demo keys (keys/turnproof-demo-2026.{pem,pub})
make demo CLIP=clips/clip1   run the full pipeline on one clip (uses API; caches responses)
make replay RUN=<run_id>     re-run from cached API responses, no network
make serve        start the review console on :8080
make verify PACKET=data/runs/<run_id>/packets/<id>.json   run verify_packet.py
make tamper PACKET=...       copy the run, flip one pixel in one display frame, run verify (expected FAIL)
make metrics RUN=<run_id>    print run_metrics.json
make test         ruff + pytest (offline)
make smoke        live API smoke test on clip 1
make video-assets RUN=<run_id>   export overlays, timeline PNG, packet PDF for the recording
```

- Ports and paths are the only environment-specific values; everything else is in `config.yaml`.
- The console works fully from cache (`make replay`), so the live demo and the recording do not depend on the API being up.
- No GPU, no system dependencies beyond ffmpeg and libgl1.

## Build plan

&#91;embedded content: build plan · 5 days, one engineer, video on day 3\]

The video is recorded on Tuesday 3 Nov so that Wednesday is editing and buffer, not building; if the schedule slips, the cut order below is applied in sequence and nothing on the never-cut list is touched.

**Deliverables by day (end of day, IST)**

1. **Day 0, Sat 31 Oct.** API key and credits; SAM on one image and one 10 s video with boxes parsed; Spark image call returning valid JSON; Voice Transcribe file call go/no-go; three clips downloaded with licences in `ATTRIBUTIONS.md`; repo skeleton, CI green, `ahm730_codes.yaml` copied; zone fractions eyeballed on clip 1.
2. **Day 1, Sun 1 Nov.** `ingest` (frames, hashes, encryption, blur), `perception` (concept + box-prompt tracking, cached responses), `zones`, `events` (hysteresis, milestones, candidate, event log). `turnproof run clips/clip1` prints the three milestones.
3. **Day 2, Mon 2 Nov.** Claim and log ingestion; discrepancy table; Spark adapter with schema and override; packet build, canonical hash, Ed25519 signature; `verify_packet.py`; JSON and PDF export; all clips run; `run_metrics.json`; fixtures recorded; `docs/VIDEO_SCRIPT.md` written.
4. **Day 3, Tue 3 Nov.** Review console (two roles), state machine wired, failure paths (unsynced, forced timeout, low confidence), Docker, tests passing offline, README with Mermaid diagram, Voice Transcribe (P2). Evening: record every screen capture and the voice-over.
5. **Day 4, Wed 4 Nov.** Edit the video; secrets scan; attribution and licence check; README final; submission form; submit by 23:00 IST. Deadline is 07:30 IST Thursday.

**Cut order if behind (apply top to bottom)**

1. Third clip → two clips.
2. PDF → HTML print view.
3. Docker → Makefile only.
4. Airline-role UI → API call shown in a terminal.
5. Voice Transcribe feature.
6. Spark dispute-note draft.
7. `baggage cart` second class.

**Never cut:** SAM-driven milestones with aircraft-relative zones; Spark JSON check with one visible override; hash-before-redaction, signature and the tamper test; run metrics on screen; the 3-minute video.

## Demo video script (180 s)

The video is judged before anything else is opened; the dispute, the packet and the tamper test must all land by 140 s, and every claim on screen must be something the repo reproduces.

| Time | Beat | On screen | Voice-over (plain, no jargon) |
| --- | --- | --- | --- |
| 0–20 s | The dispute | Title card (DAARS navy/orange); synthetic MVT line "DL32 / 9 min"; the SLA malus clause; the handler's paper-style log | "Flight XY123 left late. The airline coded nine minutes to the ground handler. Under the SLA the handler pays for them. Its only defence today is a handwritten log." |
| 20–50 s | Upload and perception | Four-file upload; SAM prompt `aircraft` typed; the aircraft outline appears and the hold regions are derived from it; prompt `belt loader`; the loader is tracked across frames | "We upload the clip and two small files. SAM 3.1 finds the aircraft from a text prompt and derives the hold regions from its outline, then tracks the belt loader." |
| 50–85 s | Milestones and discrepancy | Timeline fills: docked 17:58:04, departed 18:07:38, door closed 18:08:10; discrepancy table: video vs handler log vs airline claim | "Geometry turns the track into milestones. Loading finished at 18:07:38. The nine claimed minutes fall after that." |
| 85–110 s | Spark facts, one rejection | Spark JSON: observed facts, door state, agree/disagree; a second candidate flagged `requires_operator_review`; operator rejects it with a note; the first is confirmed | "Muse Spark reads the keyframes and returns structured facts, never a verdict. Here it disagrees with a rule candidate, so a human rejects it. The real one is confirmed." |
| 110–140 s | Packet and tamper test | Export; PDF; airline view with Acknowledge/Dispute; terminal: `verify_packet.py` all PASS; one pixel changed; FAIL | "The packet is signed. The airline runs the verifier itself. Change one pixel and it fails." |
| 140–165 s | Holds up | Clip 3 banner `unsynced`; forced API timeout retried; `run_metrics.json` with cost and latency; CI badge; `docker compose up` | "No reference clock: flagged, not hidden. API timeout: retried, recorded. Cost per packet, latency per stage, tests in CI, one command to run." |
| 165–180 s | Who, limits, next | Company line; limitations card: synthetic dispute data, three clips, indicative metrics; next step: one-station pilot | "Built this week on Meta's Model API by DAARS. Next: one station, real disputes." |

**Recording rules:** record from the cached run (`make replay`) so nothing depends on the live API; 1080p, 30 fps; cursor visible; no music under speech; every number on screen matches `run_metrics.json` and the packet; the data label is visible in every console shot; no team names other than the two founders; no "deployed".

## Submission checklist

Submission closes Wed 4 Nov 2026, 9:00 PM ET (Thu 5 Nov, 07:30 IST); the target is 23:00 IST on Wednesday, with every item below ticked before the form is sent.

- [ ] Track confirmed as Startup on the portal; one submission; team listed (two founders)
- [ ] Repo public, created after 26 Oct, first commit after kickoff, no imported code from other DAARS products
- [ ] README: what/why, architecture diagram, quickstart (`make setup`, `make replay`, `make serve`), metrics table, limitations, licence, attributions
- [ ] `ATTRIBUTIONS.md` lists every clip with source URL and licence; end-card credit in the video
- [ ] LICENSE (Apache-2.0), SECURITY.md, `.env.example`; secrets scan clean; no `.env`, keys or raw clips committed (public key only)
- [ ] CI green on `main`; `make test` passes offline
- [ ] `make replay` reproduces the demo run from cached responses without an API key
- [ ] Standard-mode model IDs only; no `-contributor`
- [ ] Data label "synthetic test data on licensed footage" visible in UI, packet and video
- [ ] Video: 3:00 or under, 1080p, uploaded; every number matches the packet and `run_metrics.json`
- [ ] Tamper test shown; verifier exit codes correct
- [ ] Company claims limited to the allowed list (deep-tech company, DPIIT-recognised, founder background, platform "in evaluation", built this week on Meta models)
- [ ] Limitations stated: synthetic dispute data, N clips, indicative metrics, footage access unvalidated
- [ ] Submission form fields filled from `docs/SUBMISSION.md` (title, one-liner, theme, models used, repo link, video link)
- [ ] Final `git tag v0.1-hackathon`; screenshots of the form and the confirmation saved

**After submission (hard stop on build):** no code changes until judging ends 8 Nov; prepare the two-minute live demo on cached results for the 9 Nov final in case of a top-10 call; start the validation gates from the design doc (footage access, one handler conversation, admissibility test) — those decide whether this becomes a product.
