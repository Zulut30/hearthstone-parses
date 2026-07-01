from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.refresh_log import build_summary, log_action
from app.storage import save_status


class OpsSummaryTest(unittest.TestCase):
    def test_summary_includes_weak_sources(self) -> None:
        with TemporaryDirectory() as td:
            with patch("app.storage.data_dir", return_value=Path(td)):
                save_status(
                    "hsreplay_arena_cards_advanced",
                    {
                        "source_id": "hsreplay_arena_cards_advanced",
                        "state": "ok",
                        "backend": "hsreplay_api",
                        "quality_score": 0.80,
                        "rows_total": 1000,
                    },
                )
                log_action(
                    "dataset.preserve_previous_good",
                    source_id="hsreplay_arena_cards_advanced",
                    level="warn",
                    detail="regression gate",
                )

                summary = build_summary(since_hours=24)

        weak = summary["weak_sources"]
        arena = next(item for item in weak if item["source_id"] == "hsreplay_arena_cards_advanced")
        self.assertEqual(arena["risk"], "medium")
        self.assertEqual(arena["preserved_count_24h"], 1)
        self.assertEqual(arena["quality_score"], 0.80)


if __name__ == "__main__":
    unittest.main()
