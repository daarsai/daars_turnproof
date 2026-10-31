from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from turnproof.evidence.canonical import packet_hash
from turnproof.evidence.sign import load_private, load_public, sign_hash, verify_hash


def test_sign_and_verify_roundtrip(tmp_path):
    priv = ed25519.Ed25519PrivateKey.generate()
    (tmp_path / "k.pem").write_bytes(
        priv.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    (tmp_path / "k.pub").write_bytes(
        priv.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    packet = {"packet_id": "TP-1", "milestones": [{"name": "loading_complete", "t_utc": "x"}]}
    h = packet_hash(packet)
    sig = sign_hash(load_private(tmp_path / "k.pem"), h, "turnproof-demo-2026")
    pub = load_public(tmp_path / "k.pub")
    assert verify_hash(pub, h, sig)
    packet["milestones"][0]["t_utc"] = "y"
    assert not verify_hash(pub, packet_hash(packet), sig)
