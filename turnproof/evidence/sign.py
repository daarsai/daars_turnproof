"""Ed25519 signing of packet hashes."""

from __future__ import annotations

import base64
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519


def load_private(path: str | Path) -> ed25519.Ed25519PrivateKey:
    key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    assert isinstance(key, ed25519.Ed25519PrivateKey)
    return key


def load_public(path: str | Path) -> ed25519.Ed25519PublicKey:
    key = serialization.load_pem_public_key(Path(path).read_bytes())
    assert isinstance(key, ed25519.Ed25519PublicKey)
    return key


def sign_hash(priv: ed25519.Ed25519PrivateKey, hex_hash: str, key_id: str) -> dict:
    sig = priv.sign(bytes.fromhex(hex_hash))
    return {"alg": "Ed25519", "key_id": key_id, "sig_base64": base64.b64encode(sig).decode()}


def verify_hash(pub: ed25519.Ed25519PublicKey, hex_hash: str, signature: dict) -> bool:
    try:
        pub.verify(base64.b64decode(signature["sig_base64"]), bytes.fromhex(hex_hash))
        return True
    except (InvalidSignature, KeyError, ValueError):
        return False
