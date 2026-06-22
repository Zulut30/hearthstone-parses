from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.hsreplay_arena_api import _class_name, fetch_class_stats


class HsreplayArenaApiTest(unittest.TestCase):
    def test_class_names_use_readable_multiword_labels(self) -> None:
        self.assertEqual(_class_name(1), "Death Knight")
        self.assertEqual(_class_name(14), "Demon Hunter")

    def test_fetch_class_stats_filters_aggregate_dual_class_rows(self) -> None:
        payload = {
            "data": [
                {"deck_class": 1, "win_rate": 50.0, "num_drafts": 100, "pick_rate": 10.0},
                {"deck_class": 2, "win_rate": 51.0, "num_drafts": 120, "pick_rate": 12.0},
                {"deck_class": 14, "win_rate": 52.0, "num_drafts": 130, "pick_rate": 13.0},
            ],
            "dual_class_data": [
                {"deck_class": 1, "secondary_deck_class": 2, "win_rate": 53.0},
                {"deck_class": 2, "secondary_deck_class": 1, "win_rate": 47.0},
                {"deck_class": 1, "secondary_deck_class": None, "win_rate": 50.0},
                {"deck_class": None, "secondary_deck_class": 1, "win_rate": 50.0},
                {"deck_class": 1, "secondary_deck_class": 1, "win_rate": 50.0},
                {"deck_class": 1, "secondary_deck_class": 99, "win_rate": 50.0},
                {"deck_class": 14, "secondary_deck_class": 1, "win_rate": 55.0},
                {"deck_class": 1, "secondary_deck_class": 14, "win_rate": 45.0},
                {"deck_class": 2, "secondary_deck_class": 14, "win_rate": 54.0},
                {"deck_class": 14, "secondary_deck_class": 2, "win_rate": 46.0},
            ],
        }

        with patch("app.hsreplay_arena_api.fetch_hsreplay_json", new=AsyncMock(return_value=payload)):
            result = asyncio.run(fetch_class_stats())

        self.assertEqual(result["expected_matchups"], 6)
        self.assertEqual(result["raw_matchups"], 10)
        self.assertEqual(len(result["matchups"]), 6)
        self.assertTrue(all(row["class_a"] and row["class_b"] for row in result["matchups"]))
        self.assertIn("Death Knight", {row["class"] for row in result["classes"]})
        self.assertIn("Demon Hunter", {row["class"] for row in result["classes"]})


if __name__ == "__main__":
    unittest.main()
