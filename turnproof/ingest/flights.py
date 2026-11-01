"""Flight context: which aircraft is on which stand, from when to when.

Two feed adapters with one output shape (a list of Flight):
  * AODB-style file (JSON) — what an airport operational database or a handler's ops system
    exports: flight, stand, scheduled/estimated/actual times, on-block and off-block.
  * Live ADS-B via the OpenSky Network REST API — gives real arrivals and landing times for an
    ICAO airport; it does NOT know stands or on-block times (those come from the AODB), so
    flights from this adapter show up as "landed, stand unknown" until the AODB fills them.

The scheduler pairs flights with stand cameras: a flight on a stand with a registered camera
gets a capture window from on-block to off-block. Nothing is detected here; this only decides
WHEN to record WHICH camera, and which claim the resulting run belongs to.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from turnproof.ingest.camera import Camera

MAX_CAPTURE_S = 45 * 60  # a turnaround window longer than this is cut (configurable later)


@dataclass
class Flight:
    flight_number: str
    airline: str
    station: str  # IATA station code, e.g. BLR
    flight_date: str  # YYYY-MM-DD
    stand: str | None
    registration: str | None
    sta_utc: str | None
    eta_utc: str | None
    landed_utc: str | None
    on_block_utc: str | None
    off_block_utc: str | None
    status: str  # scheduled | airborne | landed | on_block | off_block | departed
    source: str  # aodb_file | adsb_opensky | ...

    def public(self) -> dict:
        return asdict(self)


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s).astimezone(UTC) if s else None


def _iso(d: datetime | None) -> str | None:
    return d.isoformat(timespec="seconds").replace("+00:00", "Z") if d else None


# ---- adapter 1: AODB-style file --------------------------------------------------------------
def load_aodb_file(path: Path) -> list[Flight]:
    """JSON: {"station": "BLR", "flights": [{flight_number, airline, flight_date, stand,
    registration, sta_utc, eta_utc, landed_utc, on_block_utc, off_block_utc, status}]}"""
    doc = json.loads(path.read_text())
    station = doc.get("station", "")
    out = []
    for f in doc.get("flights", []):
        out.append(
            Flight(
                flight_number=f["flight_number"],
                airline=f.get("airline", ""),
                station=f.get("station", station),
                flight_date=f.get("flight_date") or (f.get("on_block_utc") or "")[:10],
                stand=f.get("stand"),
                registration=f.get("registration"),
                sta_utc=f.get("sta_utc"),
                eta_utc=f.get("eta_utc"),
                landed_utc=f.get("landed_utc"),
                on_block_utc=f.get("on_block_utc"),
                off_block_utc=f.get("off_block_utc"),
                status=f.get("status") or ("on_block" if f.get("on_block_utc") else "scheduled"),
                source="aodb_file",
            )
        )
    return out


# ---- adapter 2: live ADS-B (OpenSky Network) ---------------------------------------------------
OPENSKY_URL = "https://opensky-network.org/api/flights/arrival"


def opensky_arrivals(icao: str, hours: float = 2.0, station_iata: str = "") -> list[Flight]:
    """Arrivals at an ICAO airport in the last `hours` (anonymous API: limited rate, data is
    delayed by a few minutes; raises httpx errors so the console can show them)."""
    end = datetime.now(UTC)
    begin = end - timedelta(hours=hours)
    with httpx.Client(timeout=30) as c:
        r = c.get(
            OPENSKY_URL,
            params={"airport": icao, "begin": int(begin.timestamp()), "end": int(end.timestamp())},
        )
        r.raise_for_status()
        rows = r.json() or []
    out = []
    for row in rows:
        landed = datetime.fromtimestamp(row.get("lastSeen", 0), tz=UTC)
        callsign = (row.get("callsign") or "").strip() or row.get("icao24", "")
        out.append(
            Flight(
                flight_number=callsign,
                airline="",
                station=station_iata or icao,
                flight_date=landed.strftime("%Y-%m-%d"),
                stand=None,
                registration=None,
                sta_utc=None,
                eta_utc=None,
                landed_utc=_iso(landed),
                on_block_utc=None,
                off_block_utc=None,
                status="landed",
                source="adsb_opensky",
            )
        )
    return sorted(out, key=lambda f: f.landed_utc or "", reverse=True)


# ---- scheduler: flights x cameras -> capture windows --------------------------------------------
@dataclass
class CaptureWindow:
    flight: Flight
    camera: Camera
    start_utc: str
    end_utc: str
    seconds: float
    state: str  # planned | due | missed | no_camera

    def public(self) -> dict:
        return {
            "flight": self.flight.public(),
            "camera": self.camera.public(),
            "start_utc": self.start_utc,
            "end_utc": self.end_utc,
            "seconds": self.seconds,
            "state": self.state,
        }


def plan(
    flights: list[Flight], cameras: list[Camera], now: datetime | None = None
) -> list[CaptureWindow]:
    """One capture window per flight that has an on-block time and a stand with a camera.
    `due` = now is inside the window (record now); `planned` = window in the future;
    `missed` = window already closed (the VMS export is the fallback)."""
    now = now or datetime.now(UTC)
    by_stand = {(c.station, c.stand): c for c in cameras}
    out = []
    for f in flights:
        if not f.on_block_utc or not f.stand:
            continue
        cam = by_stand.get((f.station, f.stand))
        if cam is None:
            continue
        start = _dt(f.on_block_utc)
        end = _dt(f.off_block_utc) or (start + timedelta(seconds=MAX_CAPTURE_S))
        seconds = min(MAX_CAPTURE_S, max(10.0, (end - start).total_seconds()))
        if now < start:
            state = "planned"
        elif now < end:
            state = "due"
        else:
            state = "missed"
        out.append(CaptureWindow(f, cam, _iso(start), _iso(end), seconds, state))
    return out


def flights_without_camera(flights: list[Flight], cameras: list[Camera]) -> list[Flight]:
    stands = {(c.station, c.stand) for c in cameras}
    return [f for f in flights if f.stand and (f.station, f.stand) not in stands]
