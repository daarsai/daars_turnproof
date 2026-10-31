import pytest

from turnproof.events.eventlog import EventLog
from turnproof.evidence.canonical import (
    chain_genesis,
    chain_next,
    hash_obj,
    packet_hash,
    rebuild_chain,
)


def test_canonical_is_order_independent():
    assert hash_obj({"a": 1, "b": [1, 2]}) == hash_obj({"b": [1, 2], "a": 1})


def test_packet_hash_excludes_signature_fields():
    p = {"x": 1, "packet_sha256": "zzz", "signature": {"sig_base64": "q"}}
    assert packet_hash(p) == hash_obj({"x": 1})


def test_chain_rebuilds_and_detects_tamper(tmp_path):
    log = EventLog(tmp_path / "e.db", "run-1")
    assert log.head() == chain_genesis("run-1")
    for i in range(5):
        log.append("system", "candidate_created", {"i": i}, None, "CANDIDATE")
    recs = log.records()
    assert rebuild_chain("run-1", recs) == log.head()
    recs[2]["action"] = "review_confirmed"  # tamper
    with pytest.raises(ValueError, match="seq 3"):
        rebuild_chain("run-1", recs)


def test_chain_next_is_deterministic():
    r = {"seq": 1, "actor": "system"}
    assert chain_next("abc", r) == chain_next("abc", {**r, "hash": "ignored"})


def test_unknown_actor_rejected(tmp_path):
    log = EventLog(tmp_path / "e.db", "run-1")
    with pytest.raises(ValueError):
        log.append("muse_spark", "x", {})
