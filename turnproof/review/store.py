"""Review state for the console: one review.json per run, every decision appended to the
run's hash-chained event log. Reads run folders under data/runs/.

The console never edits run_summary.json, packets, frames or the event log in place.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from turnproof.events.eventlog import EventLog
from turnproof.evidence import packet as packet_mod
from turnproof.review.state_machine import TRANSITIONS, Candidate, TransitionError

ROLE_ACTOR = {"handler": "handler_operator", "airline": "airline_reviewer"}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class RunStore:
    def __init__(self, data_dir: Path = Path("data")):
        self.runs_dir = data_dir / "runs"

    # ---- listing ----------------------------------------------------------
    def run_ids(self) -> list[str]:
        if not self.runs_dir.exists():
            return []
        ids = [p.parent.name for p in self.runs_dir.glob("*/run_summary.json")]
        return sorted(ids, key=lambda r: self.summary(r).get("created_at_utc", ""), reverse=True)

    def run_dir(self, run_id: str) -> Path:
        if not run_id or "/" in run_id or run_id.startswith("."):
            raise FileNotFoundError(run_id)
        d = self.runs_dir / run_id
        if not (d / "run_summary.json").exists():
            raise FileNotFoundError(run_id)
        return d

    def summary(self, run_id: str) -> dict:
        return json.loads((self.run_dir(run_id) / "run_summary.json").read_text())

    def metrics(self, run_id: str) -> dict | None:
        p = self.run_dir(run_id) / "run_metrics.json"
        return json.loads(p.read_text()) if p.exists() else None

    def occupancy(self, run_id: str) -> dict | None:
        p = self.run_dir(run_id) / "occupancy.json"
        return json.loads(p.read_text()) if p.exists() else None

    def events(self, run_id: str) -> list[dict]:
        p = self.run_dir(run_id) / "eventlog.jsonl"
        if not p.exists():
            return []
        return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]

    # ---- packets ------------------------------------------------------------
    def packet_path(self, run_id: str) -> Path | None:
        s = self.summary(run_id)
        if not s.get("packet"):
            return None
        p = self.run_dir(run_id) / "packets" / Path(s["packet"]).name
        return p if p.exists() else None

    def packet(self, run_id: str) -> dict | None:
        p = self.packet_path(run_id)
        return json.loads(p.read_text()) if p else None

    def find_packet(self, packet_id: str) -> tuple[str, dict] | None:
        for rid in self.run_ids():
            p = self.packet_path(rid)
            if p and p.stem == packet_id:
                return rid, json.loads(p.read_text())
        return None

    # ---- review state -------------------------------------------------------
    def review(self, run_id: str) -> dict:
        d = self.run_dir(run_id)
        p = d / "review.json"
        if p.exists():
            return json.loads(p.read_text())
        s = self.summary(run_id)
        spark = s.get("spark") or {}
        has_candidate = s.get("status") in ("candidate", "candidate_unsynced")
        if not has_candidate:
            state = "OBSERVED"
        elif spark.get("ok"):
            state = "UNDER_REVIEW"
        else:
            state = "CANDIDATE"
        c = Candidate(
            candidate_id=run_id,
            state=state,
            requires_operator_review=bool(spark.get("requires_operator_review", True)),
            spark_confidence=float(spark.get("confidence") or 0.0),
        )
        return {**asdict(c), "statement": None, "updated_at_utc": None}

    def available_actions(self, run_id: str, role: str) -> list[str]:
        st = self.review(run_id)["state"]
        actor = ROLE_ACTOR.get(role)
        return [
            action
            for (frm, action), (actors, _to) in TRANSITIONS.items()
            if frm == st and actor in actors
        ]

    def transition(self, run_id: str, role: str, action: str, note: str = "") -> dict:
        actor = ROLE_ACTOR.get(role)
        if actor is None:
            raise TransitionError(f"unknown role {role!r}")
        rev = self.review(run_id)
        c = Candidate(
            candidate_id=rev["candidate_id"],
            state=rev["state"],
            requires_operator_review=rev["requires_operator_review"],
            spark_confidence=rev["spark_confidence"],
            confidence_floor=rev.get("confidence_floor", 0.70),
            history=list(rev.get("history", [])),
        )
        prev = c.state
        c.transition(actor, action, note)  # raises TransitionError if not allowed
        c.history[-1]["t_utc"] = _now()
        d = self.run_dir(run_id)
        log = EventLog(d / "events.db", run_id)
        log.append(actor, action, {"note": note}, prev, c.state)
        out = {**asdict(c), "statement": rev.get("statement"), "updated_at_utc": _now()}
        if action in ("send", "acknowledge", "dispute"):
            self._reissue_packet(run_id, out, action, note, log)
        log.export_jsonl(d / "eventlog.jsonl")
        (d / "review.json").write_text(json.dumps(out, indent=1))
        return out

    def _reissue_packet(
        self, run_id: str, rev: dict, action: str, note: str, log: EventLog
    ) -> None:
        """On send: a new signed packet version carrying the decision, note and statement.
        On acknowledge / dispute: another version carrying the airline's answer."""
        path = self.packet_path(run_id)
        if not path:
            return
        draft = json.loads(path.read_text())
        confirm = next((h for h in rev["history"] if h["action"] == "confirm"), None)
        review = {
            "decision": "confirmed" if confirm else "pending",
            "operator": "handler_operator",
            "t_utc": (confirm or {}).get("t_utc"),
            "note": (confirm or {}).get("note", ""),
        }
        counterparty = None
        if action in ("acknowledge", "dispute"):
            counterparty = {
                "state": "ACKNOWLEDGED" if action == "acknowledge" else "DISPUTED",
                "actor": "airline_reviewer",
                "t_utc": _now(),
                "reason": note or None,
            }
        key_id = draft["signature"]["key_id"]
        new = packet_mod.reissue(
            draft,
            path,
            key_id,
            review=review,
            counterparty=counterparty,
            human_statement=rev.get("statement"),
            chain_head=log.head(),
        )
        log.append(
            "system",
            "packet_reissued",
            {"packet_sha256": new["packet_sha256"], "prev": draft["packet_sha256"], "on": action},
        )

    # ---- operator statement (typed, or spoken -> Muse Voice Transcribe) ----------------
    def set_statement(self, run_id: str, statement: dict) -> dict:
        d = self.run_dir(run_id)
        rev = self.review(run_id)
        rev["statement"] = statement
        log = EventLog(d / "events.db", run_id)
        log.append("handler_operator", "statement_recorded", statement)
        log.export_jsonl(d / "eventlog.jsonl")
        (d / "review.json").write_text(json.dumps(rev, indent=1))
        return rev
