import os

import pytest
from cryptography.exceptions import InvalidTag
from pydantic import ValidationError

from turnproof.ingest.crypto import decrypt, hash_and_encrypt
from turnproof.reason.schemas import SparkOut


def test_hash_is_of_original_and_roundtrip(tmp_path):
    key = os.urandom(32)
    data = b"\x89PNG fake frame bytes"
    h = hash_and_encrypt(data, "f0001", tmp_path / "enc" / "f0001.bin", key)
    assert len(h) == 64
    assert decrypt(tmp_path / "enc" / "f0001.bin", "f0001", key) == data
    with pytest.raises(InvalidTag):
        decrypt(tmp_path / "enc" / "f0001.bin", "f0002", key)  # wrong frame id = tamper


GOOD = {
    "observed_facts": [{"text": "Loader clear of aft hold", "frames": ["f2452"]}],
    "hold_door_state": "closed",
    "rule_claim_check": {"claim": "loader_departed", "agree": True, "reason": "visible"},
    "candidate_delay_code_family": "32",
    "confidence": 0.84,
    "requires_operator_review": False,
}


def test_spark_schema_accepts_good():
    assert SparkOut.model_validate(GOOD).confidence == 0.84


@pytest.mark.parametrize(
    "bad",
    [
        {**GOOD, "possible_causes": ["x"]},  # extra key forbidden
        {**GOOD, "candidate_delay_code_family": "32A"},  # final code, not family
        {**GOOD, "hold_door_state": "ajar"},
        {**GOOD, "confidence": 1.4},
        {k: v for k, v in GOOD.items() if k != "requires_operator_review"},
    ],
)
def test_spark_schema_rejects_bad(bad):
    with pytest.raises(ValidationError):
        SparkOut.model_validate(bad)
