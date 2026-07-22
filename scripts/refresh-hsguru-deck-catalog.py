#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.hsguru_decks import refresh_hsguru_deck_catalog  # noqa: E402


async def main() -> None:
    standard, wild = await asyncio.gather(
        refresh_hsguru_deck_catalog("standard"),
        refresh_hsguru_deck_catalog("wild"),
    )
    print(json.dumps({
        "state": "ok",
        "standard_decks": len(standard),
        "wild_decks": len(wild),
    }))


if __name__ == "__main__":
    asyncio.run(main())
