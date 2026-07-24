from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.routers.hsguru_meta import hsguru_archetype_analysis


DATASET = {
    "fetched_at": "2026-07-24T00:00:00+00:00",
    "data": {
        "structured": {
            "type": "hsguru_archetype_analysis",
            "archetypes": [
                {
                    "format": "standard",
                    "archetype": "Void Soul DH",
                    "rank": "legend",
                    "period": "past_week",
                    "updated_at": "2026-07-24T01:00:00+00:00",
                    "class_matchups": [{"class_key": "mage", "winrate": 52.3}],
                    "card_stats": [{"card_id": "TOY_330", "mulligan_impact": 4.8}],
                }
            ],
        }
    },
}


class HSGuruArchetypeAnalysisApiTest(unittest.TestCase):
    def test_returns_exact_format_and_case_insensitive_archetype(self) -> None:
        with patch("app.routers.hsguru_meta.load_dataset", return_value=DATASET):
            payload = hsguru_archetype_analysis(
                archetype="void soul dh",
                format_name="standard",
            )

        self.assertEqual(payload["data"]["rank"], "legend")
        self.assertEqual(payload["data"]["class_matchups"][0]["class_key"], "mage")
        self.assertEqual(payload["meta"]["source_id"], "hsguru_archetype_analysis")

    def test_returns_not_found_for_missing_analysis(self) -> None:
        with (
            patch("app.routers.hsguru_meta.load_dataset", return_value=DATASET),
            self.assertRaises(HTTPException) as raised,
        ):
            hsguru_archetype_analysis(
                archetype="Quest Mage",
                format_name="standard",
            )

        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
