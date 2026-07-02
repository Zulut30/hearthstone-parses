from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.hsreplay_arena_api import _class_name, fetch_class_stats


class HsreplayArenaApiTest(unittest.TestCase):
    def test_class_names_use_titlecased_cardclass_enum_labels(self) -> None:
        # _class_name titles the hearthstone CardClass enum name
        # (app/hsreplay_arena_api.py:74-80): DEATHKNIGHT -> "Deathknight",
        # DEMONHUNTER -> "Demonhunter". This single-word form is the canonical
        # `class` value across the app: app/hsreplay_arena_classes_firecrawl.py:14
        # uses "Deathknight" as `class` (the multiword "Death Knight" lives in the
        # separate display field `class_name`), and app/db.py:40 normalizes it.
        self.assertEqual(_class_name(1), "Deathknight")
        self.assertEqual(_class_name(14), "Demonhunter")
        self.assertIsNone(_class_name(None))
        self.assertIsNone(_class_name(99))

    def test_fetch_class_stats_returns_classes_and_empty_matchups(self) -> None:
        # Dual-class arena was permanently removed from the game, so
        # fetch_class_stats no longer reads "dual_class_data" at all: it parses
        # classes and always returns matchups=[] (kept for dataset-shape
        # compatibility until Phase 8). The quality gate validates classes only.
        payload = {
            "data": [
                {"deck_class": 1, "win_rate": 50.0, "num_drafts": 100, "pick_rate": 10.0},
                {"deck_class": 2, "win_rate": 51.0, "num_drafts": 120, "pick_rate": 12.0},
                {"deck_class": 14, "win_rate": 52.0, "num_drafts": 130, "pick_rate": 13.0},
            ],
            # even a legacy payload that still carries dual_class_data is ignored
            "dual_class_data": [
                {"deck_class": 1, "secondary_deck_class": 2, "win_rate": 53.0},
            ],
        }

        with patch("app.hsreplay_arena_api.fetch_hsreplay_json", new=AsyncMock(return_value=payload)):
            result = asyncio.run(fetch_class_stats())

        self.assertEqual(result["type"], "arena_class_matrix")
        self.assertEqual(result["matchups"], [])
        self.assertEqual(len(result["classes"]), 3)
        # classes are sorted by win_rate desc
        self.assertEqual(
            [row["win_rate"] for row in result["classes"]],
            [52.0, 51.0, 50.0],
        )
        self.assertIn("Deathknight", {row["class"] for row in result["classes"]})
        self.assertIn("Demonhunter", {row["class"] for row in result["classes"]})


if __name__ == "__main__":
    unittest.main()
