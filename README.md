# TurnProof

Video-backed, delay-code-linked turnaround evidence packets for airport ground handlers.
Upload one stand-camera clip plus the airline's delay claim and your own milestone log;
get a signed, hash-verified packet the airline can verify without us.

Built during the Meta Global AI Developer Hackathon 2026 (Startup track) on the Meta Model API:
SAM 3.1 for text-prompted detection, aircraft-relative zones and tracking; Muse Spark 1.3 for
structured keyframe facts that can flag a candidate but never decide it.

> All flight, claim and log data in this repository and the demo are **synthetic test data** on
> licensed footage (see `ATTRIBUTIONS.md`). Accuracy figures are indicative, from N clips only.

## Quickstart

```bash
make setup                          # venv, deps, demo keys, .env from template
# put MODEL_API_KEY in .env
make frames CLIP=clips/clip1.mp4    # 1 fps PNGs + 10 s excerpt
make smoke-sam IMG=data/frames/clip1/f0000.png PROMPT="belt loader"
make smoke-spark IMG="data/frames/clip1/f0010.png data/frames/clip1/f0020.png"
make test
```

Pipeline, console, verifier and video script: see `docs/SPEC.md`.

## Status

Day 0 (31 Oct 2026): skeleton, integrity core (canonical JSON, hash chain, Ed25519), smoke scripts.
