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
from app.hsguru_meta_matrix import refresh_current_catalog_deck_join  # noqa: E402


async def main() -> None:
    standard_legend, wild_legend = await asyncio.gather(
        refresh_hsguru_deck_catalog("standard"),
        refresh_hsguru_deck_catalog("wild"),
    )
    standard_all, wild_all = await asyncio.gather(
        refresh_hsguru_deck_catalog("standard", "all"),
        refresh_hsguru_deck_catalog("wild", "all"),
    )
    archetype_join = refresh_current_catalog_deck_join()
    print(json.dumps({
        "state": "ok",
        "standard_legend_decks": len(standard_legend),
        "wild_legend_decks": len(wild_legend),
        "standard_all_decks": len(standard_all),
        "wild_all_decks": len(wild_all),
        "archetype_join": archetype_join,
    }))


if __name__ == "__main__":
    asyncio.run(main())
