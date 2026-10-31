import pytest

from turnproof.review.state_machine import Candidate, TransitionError


def fresh(**kw):
    c = Candidate("c1", **kw)
    c.transition("system", "milestones_detected")
    c.transition("system", "spark_evaluated")
    return c


def test_happy_path_to_acknowledged():
    c = fresh(requires_operator_review=False, spark_confidence=0.9)
    c.transition("handler_operator", "confirm")
    c.transition("handler_operator", "send")
    assert c.transition("airline_reviewer", "acknowledge") == "ACKNOWLEDGED"
    assert c.transition("airline_reviewer", "resolve", "settled") == "RESOLVED"
    assert c.transition("system", "archive") == "ARCHIVED"


def test_wrong_actor_rejected():
    c = fresh(requires_operator_review=False, spark_confidence=0.9)
    with pytest.raises(TransitionError):
        c.transition("airline_reviewer", "confirm")
    with pytest.raises(TransitionError):
        c.transition("system", "confirm")


def test_flagged_candidate_needs_override_note():
    c = fresh(requires_operator_review=True, spark_confidence=0.9)
    with pytest.raises(TransitionError):
        c.transition("handler_operator", "confirm")
    assert c.transition("handler_operator", "confirm", "checked frames manually") == "CONFIRMED"


def test_low_confidence_needs_override_note():
    c = fresh(requires_operator_review=False, spark_confidence=0.4)
    with pytest.raises(TransitionError):
        c.transition("handler_operator", "confirm")


def test_reject_requires_note_and_archives():
    c = fresh(requires_operator_review=False, spark_confidence=0.9)
    with pytest.raises(TransitionError):
        c.transition("handler_operator", "reject")
    c.transition("handler_operator", "reject", "loader parked beside hold, door closed")
    assert c.transition("system", "archive") == "ARCHIVED"


def test_no_model_actor_exists():
    c = fresh()
    with pytest.raises(TransitionError):
        c.transition("muse_spark", "confirm", "x")


def test_correction_keeps_state_and_history():
    c = fresh()
    c.transition("handler_operator", "correct", "fixed stand id")
    assert c.state == "UNDER_REVIEW"
    assert c.history[-1]["action"] == "correct"
