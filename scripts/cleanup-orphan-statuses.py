#!/usr/bin/env python3
"""Remove status/dataset files for source ids not in app.sources.SOURCES."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import data_dir
from app.sources import SOURCES


def main() -> int:
    configured = {s.id for s in SOURCES}
    removed: list[str] = []
    for subdir in ("statuses", "datasets"):
        base = data_dir() / subdir
        if not base.is_dir():
            continue
        for path in base.glob("*.json"):
            sid = path.stem
            if sid in configured:
                continue
            path.unlink(missing_ok=True)
            removed.append(f"{subdir}/{path.name}")
    print(json.dumps({"removed": removed}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
