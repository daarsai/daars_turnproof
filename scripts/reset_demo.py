"""Start the console from an empty state, without deleting anything.

Moves every run, registered claim, upload, webhook delivery and camera snapshot under data/
into data/archive/<UTC timestamp>/. Keeps the model cache (data/cache: re-running footage that
was analysed before costs nothing), the camera registry and webhook targets.

    make reset-demo            # or: python scripts/reset_demo.py [--data data]
"""

from __future__ import annotations

import argparse
import shutil
from datetime import UTC, datetime
from pathlib import Path

MOVED = ("runs", "scenarios", "uploads", "webhook_inbox", "snapshots")
KEPT = ("cache", "cameras.json", "webhooks.json", "archive")


def reset(data: Path) -> Path | None:
    present = [data / name for name in MOVED if (data / name).exists()]
    if not present:
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = data / "archive" / stamp
    dest.mkdir(parents=True, exist_ok=True)
    for p in present:
        shutil.move(str(p), str(dest / p.name))
    return dest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default="data", help="data directory (default: data)")
    args = ap.parse_args()
    data = Path(args.data)
    dest = reset(data)
    if dest is None:
        print(f"{data}/ already empty: nothing to move")
        return
    moved = ", ".join(p.name for p in sorted(dest.iterdir()))
    print(f"moved to {dest}/: {moved}")
    print(f"kept: {', '.join(k for k in KEPT if (data / k).exists())}")
    print("the console now starts with no runs and no claims; the model cache is intact")


if __name__ == "__main__":
    main()
