"""Hash-then-encrypt for original frames. Hash is taken BEFORE any redaction."""

from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from turnproof.evidence.canonical import sha256_hex

NONCE_LEN = 12


def load_data_key() -> bytes:
    raw = os.environ.get("TURNPROOF_DATA_KEY", "")
    key = base64.b64decode(raw) if raw else b""
    if len(key) != 32:
        raise RuntimeError("TURNPROOF_DATA_KEY must be 32 bytes base64 (run `make keys`)")
    return key


def hash_and_encrypt(png_bytes: bytes, frame_id: str, out_path: Path, key: bytes) -> str:
    """Return sha256 of the ORIGINAL bytes; write nonce||ciphertext||tag to out_path."""
    digest = sha256_hex(png_bytes)
    nonce = os.urandom(NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, png_bytes, frame_id.encode("utf-8"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(nonce + ct)
    return digest


def decrypt(enc_path: Path, frame_id: str, key: bytes) -> bytes:
    blob = enc_path.read_bytes()
    return AESGCM(key).decrypt(blob[:NONCE_LEN], blob[NONCE_LEN:], frame_id.encode("utf-8"))
