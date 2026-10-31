"""Generate the demo Ed25519 signing key pair and an AES-256 data key.

Writes keys/turnproof-demo-2026.pem (private, gitignored) and .pub (public, committed),
and prints a TURNPROOF_DATA_KEY line to paste into .env if it is empty.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

KEY_ID = "turnproof-demo-2026"
KEYS = Path("keys")


def main() -> None:
    KEYS.mkdir(exist_ok=True)
    priv_path, pub_path = KEYS / f"{KEY_ID}.pem", KEYS / f"{KEY_ID}.pub"
    if not priv_path.exists():
        priv = ed25519.Ed25519PrivateKey.generate()
        priv_path.write_bytes(
            priv.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        pub_path.write_bytes(
            priv.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )
        print(f"wrote {priv_path} and {pub_path}")
    else:
        print(f"{priv_path} exists; not overwritten")
    env = Path(".env")
    if env.exists() and "TURNPROOF_DATA_KEY=\n" in env.read_text() + "\n":
        key = base64.b64encode(os.urandom(32)).decode()
        env.write_text(env.read_text().replace("TURNPROOF_DATA_KEY=", f"TURNPROOF_DATA_KEY={key}"))
        print("filled TURNPROOF_DATA_KEY in .env")


if __name__ == "__main__":
    main()
