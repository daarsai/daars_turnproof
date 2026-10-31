"""Candidate state machine. Only humans and the system move states; model output never does."""

from __future__ import annotations

from dataclasses import dataclass, field

STATES = (
    "OBSERVED",
    "CANDIDATE",
    "UNDER_REVIEW",
    "CONFIRMED",
    "REJECTED",
    "SENT",
    "ACKNOWLEDGED",
    "DISPUTED",
    "RESOLVED",
    "ARCHIVED",
)

# (from_state, action) -> (allowed actors, to_state)
TRANSITIONS: dict[tuple[str, str], tuple[set[str], str]] = {
    ("OBSERVED", "milestones_detected"): ({"system"}, "CANDIDATE"),
    ("CANDIDATE", "spark_evaluated"): ({"system"}, "UNDER_REVIEW"),
    ("UNDER_REVIEW", "confirm"): ({"handler_operator"}, "CONFIRMED"),
    ("UNDER_REVIEW", "reject"): ({"handler_operator"}, "REJECTED"),
    ("UNDER_REVIEW", "correct"): ({"handler_operator"}, "UNDER_REVIEW"),
    ("CONFIRMED", "send"): ({"handler_operator"}, "SENT"),
    ("SENT", "acknowledge"): ({"airline_reviewer"}, "ACKNOWLEDGED"),
    ("SENT", "dispute"): ({"airline_reviewer"}, "DISPUTED"),
    ("ACKNOWLEDGED", "resolve"): ({"handler_operator", "airline_reviewer"}, "RESOLVED"),
    ("DISPUTED", "resolve"): ({"handler_operator", "airline_reviewer"}, "RESOLVED"),
    ("RESOLVED", "archive"): ({"system"}, "ARCHIVED"),
    ("REJECTED", "archive"): ({"system"}, "ARCHIVED"),
}

NOTE_REQUIRED = {"reject", "dispute", "resolve", "correct"}


class TransitionError(Exception):
    pass


@dataclass
class Candidate:
    candidate_id: str
    state: str = "OBSERVED"
    requires_operator_review: bool = True
    spark_confidence: float = 0.0
    confidence_floor: float = 0.70
    history: list[dict] = field(default_factory=list)

    def transition(self, actor: str, action: str, note: str = "") -> str:
        key = (self.state, action)
        if key not in TRANSITIONS:
            raise TransitionError(f"{action!r} not allowed from {self.state}")
        actors, to_state = TRANSITIONS[key]
        if actor not in actors:
            raise TransitionError(f"actor {actor!r} may not {action!r} (allowed: {sorted(actors)})")
        if action in NOTE_REQUIRED and not note.strip():
            raise TransitionError(f"{action!r} requires a note")
        if action == "confirm":
            low = self.spark_confidence < self.confidence_floor
            if (self.requires_operator_review or low) and not note.strip():
                raise TransitionError(
                    "confirm needs an override note: flagged for review or low confidence"
                )
        prev = self.state
        self.state = to_state
        self.history.append(
            {"from": prev, "action": action, "to": to_state, "actor": actor, "note": note}
        )
        return to_state
