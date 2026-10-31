"""Append-only, hash-chained event log (SQLite). No UPDATE or DELETE exists in this module."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from turnproof.evidence.canonical import chain_genesis, chain_next, hash_obj

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL, t_utc TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
  from_state TEXT, to_state TEXT, payload_sha256 TEXT NOT NULL,
  prev_hash TEXT NOT NULL, hash TEXT NOT NULL UNIQUE
);
"""

ACTORS = {"system", "handler_operator", "airline_reviewer"}


class EventLog:
    def __init__(self, db_path: str | Path, run_id: str):
        self.run_id = run_id
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute(SCHEMA)

    def head(self) -> str:
        row = self.conn.execute(
            "SELECT hash FROM events WHERE run_id=? ORDER BY seq DESC LIMIT 1", (self.run_id,)
        ).fetchone()
        return row[0] if row else chain_genesis(self.run_id)

    def append(
        self,
        actor: str,
        action: str,
        payload: dict,
        from_state: str | None = None,
        to_state: str | None = None,
    ) -> dict:
        if actor not in ACTORS:
            raise ValueError(f"unknown actor {actor!r}")
        prev = self.head()
        rec = {
            "run_id": self.run_id,
            "t_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "actor": actor,
            "action": action,
            "from_state": from_state,
            "to_state": to_state,
            "payload_sha256": hash_obj(payload),
            "prev_hash": prev,
        }
        rec["hash"] = chain_next(prev, rec)
        cur = self.conn.execute(
            "INSERT INTO events (run_id,t_utc,actor,action,from_state,to_state,payload_sha256,prev_hash,hash)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                rec["run_id"],
                rec["t_utc"],
                rec["actor"],
                rec["action"],
                rec["from_state"],
                rec["to_state"],
                rec["payload_sha256"],
                rec["prev_hash"],
                rec["hash"],
            ),
        )
        self.conn.commit()
        return {"seq": cur.lastrowid, **rec}

    def records(self) -> list[dict]:
        cols = [
            "seq",
            "run_id",
            "t_utc",
            "actor",
            "action",
            "from_state",
            "to_state",
            "payload_sha256",
            "prev_hash",
            "hash",
        ]
        rows = self.conn.execute(
            f"SELECT {','.join(cols)} FROM events WHERE run_id=? ORDER BY seq", (self.run_id,)
        ).fetchall()
        return [dict(zip(cols, r, strict=True)) for r in rows]

    def export_jsonl(self, path: str | Path) -> None:
        with Path(path).open("w") as fh:
            fh.writelines(json.dumps(rec, sort_keys=True) + "\n" for rec in self.records())
