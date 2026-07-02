from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.hsreplay_arena_api import _class_name, fetch_class_stats, normalize_dual_class_row


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

    def test_fetch_class_stats_accepts_missing_dual_class_data(self) -> None:
        # Dual-class arena was permanently removed from the game: upstream payload
        # no longer contains "dual_class_data". fetch_class_stats
        # (app/hsreplay_arena_api.py:296-321) must parse classes and return empty
        # matchups — the quality gate treats empty matchups as valid
        # (app/scrapers/quality.py:272-276).
        payload = {
            "data": [
                {"deck_class": 1, "win_rate": 50.0, "num_drafts": 100, "pick_rate": 10.0},
                {"deck_class": 2, "win_rate": 51.0, "num_drafts": 120, "pick_rate": 12.0},
                {"deck_class": 14, "win_rate": 52.0, "num_drafts": 130, "pick_rate": 13.0},
            ],
        }

        with patch("app.hsreplay_arena_api.fetch_hsreplay_json", new=AsyncMock(return_value=payload)):
            result = asyncio.run(fetch_class_stats())

        self.assertEqual(result["type"], "arena_class_matrix")
        self.assertEqual(result["matchups"], [])
        self.assertEqual(len(result["classes"]), 3)
        # classes are sorted by win_rate desc (app/hsreplay_arena_api.py:306)
        self.assertEqual(
            [row["win_rate"] for row in result["classes"]],
            [52.0, 51.0, 50.0],
        )
        self.assertIn("Deathknight", {row["class"] for row in result["classes"]})
        self.assertIn("Demonhunter", {row["class"] for row in result["classes"]})

    def test_fetch_class_stats_tolerates_legacy_dual_class_rows(self) -> None:
        # normalize_dual_class_row is kept until Phase 3 so a legacy payload with
        # "dual_class_data" is still tolerated: rows are normalized 1:1 without
        # filtering (app/hsreplay_arena_api.py:168-181, 302-305).
        payload = {
            "data": [
                {"deck_class": 1, "win_rate": 50.0, "num_drafts": 100, "pick_rate": 10.0},
                {"deck_class": 2, "win_rate": 51.0, "num_drafts": 120, "pick_rate": 12.0},
            ],
            "dual_class_data": [
                {"deck_class": 1, "secondary_deck_class": 2, "win_rate": 53.0},
                {"deck_class": 2, "secondary_deck_class": 1, "win_rate": 47.0},
                {"deck_class": 1, "secondary_deck_class": None, "win_rate": 50.0},
            ],
        }

        with patch("app.hsreplay_arena_api.fetch_hsreplay_json", new=AsyncMock(return_value=payload)):
            result = asyncio.run(fetch_class_stats())

        self.assertEqual(len(result["matchups"]), 3)
        first = result["matchups"][0]
        self.assertEqual(first["class_a"], "Deathknight")
        self.assertEqual(first["class_b"], "Druid")
        self.assertEqual(first["winrate"], "53.00%")
        # aggregate row (no secondary class) keeps class_b=None instead of being dropped
        self.assertIsNone(result["matchups"][2]["class_b"])

    def test_normalize_dual_class_row_maps_ids_to_class_names(self) -> None:
        row = normalize_dual_class_row(
            {"deck_class": 14, "secondary_deck_class": 1, "win_rate": 55.5}
        )

        self.assertEqual(row["class_a"], "Demonhunter")
        self.assertEqual(row["class_b"], "Deathknight")
        self.assertEqual(row["win_rate"], 55.5)
        self.assertEqual(row["winrate"], "55.50%")


if __name__ == "__main__":
    unittest.main()
