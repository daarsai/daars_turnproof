"""Pydantic schemas: Spark output (strict) and the evidence packet (schema_version 0.1)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CODE_FAMILY = r"^(3[1-9]|none)$"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- Muse Spark output ----------
class Fact(Strict):
    text: str
    frames: list[str]


class RuleCheck(Strict):
    claim: Literal["loader_docked", "loader_departed", "equipment_docked", "equipment_departed"]
    agree: bool
    reason: str


class SparkOut(Strict):
    observed_facts: list[Fact]
    hold_door_state: Literal["open", "closed", "unknown"]
    rule_claim_check: RuleCheck
    candidate_delay_code_family: str = Field(pattern=CODE_FAMILY)
    confidence: float = Field(ge=0, le=1)
    requires_operator_review: bool


# ---------- Evidence packet ----------
class Flight(Strict):
    number: str
    date: str
    airline: str
    registration: str | None = None


class Source(Strict):
    type: Literal["upload"]
    camera_id: str
    file_sha256: str
    fps: float
    duration_s: float


class TimeSync(Strict):
    status: Literal["declared", "measured", "unsynced"]
    reference_start_utc: str | None
    measured_offset_s: float | None
    speed_factor: float | None
    speed_factor_source: str | None
    method: str


class AirlineClaim(Strict):
    delay_code: str
    minutes: int
    source: str


class LogEntry(Strict):
    milestone: str
    t_utc: str


class Milestone(Strict):
    name: str = Field(
        pattern=r"^[a-z][a-z0-9_]{2,48}$"
    )  # <event>_docked_start, <event>_complete, hold_door_closed
    t_utc: str | None
    frame_index: int
    method: str
    zone: str
    confidence: float = Field(ge=0, le=1)
    evidence_frames: list[str]


class ObservedFact(Strict):
    text: str
    frames: list[str]
    source: str


class Discrepancy(Strict):
    milestone: str
    video_utc: str | None
    handler_log_utc: str | None
    video_minus_log_min: float | None
    note: str | None
    airline_claim_minutes: int
    video_supported_minutes: int | None
    delta_min: int | None


class ProposedClaim(Strict):
    delay_code_family: str = Field(pattern=CODE_FAMILY)
    minutes_supported_by_video: int | None
    basis: str


class EvidenceFrame(Strict):
    id: str
    t_utc: str | None
    frame_index: int
    sha256_original: str
    sha256_redacted: str
    redaction: str
    original_ref: str


class ModelInfo(Strict):
    sam: dict
    spark: dict
    asr: dict | None
    zones_config_sha256: str


class Correction(Strict):
    seq: int
    field: str
    old: str
    new: str
    t_utc: str


class Review(Strict):
    decision: Literal["pending", "confirmed", "rejected"]
    operator: str | None
    t_utc: str | None
    note: str
    corrections: list[Correction]


class Counterparty(Strict):
    state: Literal["PENDING", "ACKNOWLEDGED", "DISPUTED"]
    actor: str | None
    t_utc: str | None
    reason: str | None


class Chain(Strict):
    event_log_head_sha256: str
    prev_packet_sha256: str | None


class Signature(Strict):
    alg: Literal["Ed25519"]
    key_id: str
    sig_base64: str


class Packet(Strict):
    packet_id: str
    schema_version: Literal["0.1"]
    created_at_utc: str
    station: str
    stand: str
    flight: Flight
    parties: dict[str, str]
    data_label: str
    source: Source
    time_sync: TimeSync
    airline_claim: AirlineClaim
    handler_log: list[LogEntry]
    milestones: list[Milestone]
    observed_facts: list[ObservedFact]
    discrepancies: list[Discrepancy]
    proposed_claim: ProposedClaim
    evidence_frames: list[EvidenceFrame]
    models: ModelInfo
    human_statement: dict | None
    review: Review
    counterparty: Counterparty
    chain: Chain
    packet_sha256: str
    signature: Signature
