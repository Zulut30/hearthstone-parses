from __future__ import annotations

import unittest

from app.publish_gate import validate_candidate_for_publish
from app.sources import SOURCE_BY_ID


def _bg_hero_row(index: int) -> dict:
    return {
        "hero": f"Hero {index}",
        "dbfId": 1000 + index,
        "pick_rate": f"{index / 10:.2f}%",
        "avg_placement": f"{3.5 + (index % 15) / 20:.2f}",
        "tier": ["S", "A", "B", "C"][index % 4],
        "placement_distribution": [
            "12.50%",
            "12.50%",
            "12.50%",
            "12.50%",
            "12.50%",
            "12.50%",
            "12.50%",
            "12.50%",
        ],
    }


class PublishGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = SOURCE_BY_ID["hsreplay_battlegrounds_heroes"]
        self.parsed = {
            "title": "Battlegrounds heroes",
            "structured": {
                "type": "bg_heroes",
                "heroes": [_bg_hero_row(index) for index in range(30)],
            },
        }

    def test_firecrawl_cannot_publish_api_only_bg_heroes(self) -> None:
        result = validate_candidate_for_publish(
            self.source,
            self.parsed,
            backend="firecrawl",
        )

        self.assertFalse(result.ok)
        self.assertIn("backend policy rejected", result.reason)
        self.assertEqual(result.extra["backend"], "firecrawl")
        self.assertFalse(result.extra["backend_allowed"])

    def test_hsreplay_backend_can_publish_valid_bg_heroes(self) -> None:
        result = validate_candidate_for_publish(
            self.source,
            self.parsed,
            backend="hsreplay_premium_flaresolverr",
        )

        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.reason, "ok")
        self.assertTrue(result.extra["backend_allowed"])


if __name__ == "__main__":
    unittest.main()
