# TurnProof console: frontend status and backend dependencies

Status after the V3 frontend repair (2 Nov 2026). The console work is frontend only: templates,
`style.css` and `app.js` (V3 also added view-model code in `app.py` / `views.py`; the repair
changed no Python). Nothing below is simulated in the UI: a missing capability is either left out
or labelled as missing.

Sections:

1. Already supported by the backend.
2. Frontend-only work completed.
3. Backend work needed later.
4. Optional future features.

Items in sections 3 and 4 are not implemented.

---

## 1. Already supported by the backend

| Capability | Where |
|---|---|
| Evidence analysis of uploaded footage (SAM 3.1 + Muse Spark), status polling | `POST /upload`, `POST /api/upload`, `GET /api/runs/{id}/status` |
| Recording from a registered stand camera, then the same analysis | `POST /station/capture` |
| Camera registry: register or replace a camera; probe with one snapshot | `POST /station/cameras`, `camera.probe()` / `snapshot()` |
| Airport flight feed (file based) with stand, on-block and off-block | `ingest/flights.py` (`config/flights_demo.json` or `data/flights.json`) |
| ADS-B arrivals from OpenSky | `GET /api/station/arrivals` |
| Milestones, time sync, handler log, claim window, evidence frames per run | `run_summary.json` |
| Human review state machine, decisions with notes, operator statement | `POST /runs/{id}/action`, `/runs/{id}/statement` |
| Signed packets, re-signed with the decision (`chain.prev_packet_sha256` = the draft's hash) | `evidence/packet.py` |
| Standalone verification and tamper test | `POST /api/packets/{id}/verify`, `/tamper`, `verify_packet.py` |
| Webhook delivery to the airline and airline responses | `webhooks.py`, `/hooks/inbox` |

## 2. Frontend-only work completed

**Layout and screens**

- **Overview (V2 layout restored):**
  - KPI tiles;
  - large annotated evidence frame with previous/next and a frame strip;
  - observed events with timestamps;
  - Claim vs Evidence panel;
  - compact work queue and exceptions.
- **Evidence Review:**
  - one row per flight;
  - investigation page with the large viewer, Claim vs Evidence, Review Decision, handler-log comparison, Turnaround Timeline and a run-history drawer.
- **Turnaround Timeline:**
  - proportional UTC axis built only from stored records;
  - selecting a milestone selects its frame;
  - unsynced footage is shown in clip time, with the UTC records listed separately.
- **Airport & Cameras:**
  - flight list, then the selected stand camera with a truthful status (Live / Replay / Offline / Snapshot / Not tested);
  - two footage sources for the same flight: Record & Analyze, or Upload Footage;
  - footage on file;
  - ADS-B arrivals.
- **Manage Cameras page:** list, test & preview, register / edit (existing POST).
- **Claims and Sent Packets:**
  - claim → evidence → decision → packet → airline response in one row;
  - packets grouped by flight.
- **Workspaces:**
  - compact "Demo · role" session indicator;
  - the workspace switch is labelled demo only;
  - `/login` shows the sign-in form disabled;
  - handler pages opened in the Airline workspace show a warning.

**Rendering fixes made in the repair**

- **Stale stylesheet:** static files are served without `Cache-Control` and under unchanged URLs, so a browser could reuse the V2 stylesheet with V3 markup.
  - Effect: unsized icons filled their containers and the account menu lost its styles.
  - Fix: `style.css` / `app.js` are now loaded with a version query (`?v=3.1`). Bump it when either file changes.
- **Unbounded icons:** every icon SVG now has a fixed `width`/`height` of its own.
- **`hidden` ignored:** class rules such as `.stack { display: flex }` overrode the `hidden` attribute, so all flight panels showed at once.
  - Fix: a global `[hidden] { display: none !important }`.

## 3. Backend work needed later

### 3.1 Authentication and organisational authorisation (highest priority)

- **Now:** the workspace comes from a `tp_role` cookie set by `GET /role/{role}`. Anyone can switch, and every page can be reached by URL.
- **Needed:**
  - Server-side sessions: login, logout and expiry, with password and/or SSO (OIDC / SAML).
  - User records with organisation id, organisation type (`ground_handler` | `airline`) and role.
  - Authorisation on every route:
    - Airlines see only packets addressed to them.
    - Handlers see only their stations.
    - Handler-only POSTs (`/station/*`, `/upload`, `/intake/*`, handler actions on `/runs/*/action`) reject airline sessions.
  - "Who am I" data for the header: user, organisation, role.
  - Actor identity in the event log taken from the session, not the fixed `handler_operator` / `airline`.

### 3.2 Camera setup and management

- **Remove a camera:** no endpoint exists, so the UI does not offer removal.
- **Update keeping credentials:**
  - Editing today means re-saving with the same id, and stream credentials must be re-entered because they are redacted on display.
  - Needed: an update endpoint that keeps stored credentials unless new ones are given.
- **Stored test results:**
  - A probe lasts one page view; "Last snapshot" is the file time.
  - Needed: `last_test_utc`, `last_test_ok`, `last_error` per camera; optionally a background health check.
- **Explicit source type:**
  - Live vs Replay is a heuristic (demo registry, `speed_factor ≠ 1`, or a note starting "DEMO").
  - Needed: `source_type` (`live_camera` | `vms_export` | `test_loop`).
- **Display name:** the camera model has no `name` field.

### 3.3 Camera-to-flight associations

- **Now:** `flights.plan()` keys cameras by `(station, stand)`, so only one camera per stand gets a capture window. The UI lists the extra cameras but cannot plan them.
- **No camera on run summaries:** runs do not record which camera produced them, except capture runs (`status.json → capture.camera_id`).
- **Footage source is inferred:** "Uploaded footage" vs "Footage file" is guessed from the clip path.
- **Needed:**
  - a camera id and a `footage_source` written into every run summary;
  - several cameras per stand in `plan()`.

### 3.4 Timeline event data

- **What the timeline draws today:**
  - flight-feed times;
  - footage coverage;
  - SAM 3.1 milestones and evidence frames;
  - the handler log;
  - the claim window;
  - review decisions.
- **Several events per run:** each run detects one event (e.g. loading). Needed: multiple events per run (fuelling, catering, pushback…), each with start/end milestones and confidence. The chart can already draw more lanes.
- **Uncertainty:** it is inferred from the milestone `method` string (e.g. `present_at_clip_start`). Needed: explicit `lower_bound` / `upper_bound` and a reason.
- **Case id:** runs, claims and packets are grouped by `flight_number|flight_date` in the UI. Needed: a stored case id on all three, and an index of packet versions per case.

### 3.5 ADS-B flight matching

- **Callsigns vs flight numbers:** OpenSky returns ICAO callsigns (`AIC123`), the flight feed uses flight numbers (`AI123`), and the UI links an arrival to a stand only on an exact match.
  - Needed: a callsign ↔ flight-number mapping with a confidence per match.
- **Error status:** every OpenSky error comes back as 502 `HTTP <code>`, and the UI finds rate limiting by looking for "429" in that text.
  - Needed: pass 429 and `Retry-After` through, plus a server-side fetch time and cache.
- **Live flight feed:** the feed is a file. Needed: a live AODB / handler-ops connector with on-block and off-block updates.

### 3.6 Historical footage

There is no API to fetch archived recordings. The UI lists only footage already analysed and
says that VMS retrieval is not connected. Needed: a VMS adapter (e.g. ONVIF Profile G or a
vendor export API) that, given a camera and a time window, returns a clip into the existing
pipeline.

### 3.7 Robustness issue found in testing

- **The bug:** `jobs.write_status()` rewrites `status.json` in place, so a reader can get an empty file (`JSONDecodeError`).
- **Seen in testing:** `tests/test_upload.py` failed once in five runs because of it.
- **Needed:** atomic writes (temporary file, then `os.replace`).

## 4. Optional future features

- Several cameras per stand analysed together (synchronised multi-view evidence).
- Push updates (WebSocket / SSE) instead of page polling for run progress and airline responses.
- Long-lived static caching with build-time asset hashing (replacing the manual `?v=`).
- Per-airline branding and notification preferences in the airline workspace.

## Deployment note

The console runs on port 8090; the RTSP media service stays internal on 8554.
