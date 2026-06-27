from __future__ import annotations

import unittest

from app.scrapers.quality import validate_parsed_data
from app.source_validators import validate_structured
from app.sources import SOURCE_BY_ID


def _hero_row(idx: int, *, name: str | None = None, avg: str | None = None) -> dict:
    place_one = 20.0 + (idx % 5) * 0.1
    rest = round((100.0 - place_one) / 7, 2)
    distribution = [f"{place_one:.2f}%"] + [f"{rest:.2f}%"] * 6
    distribution.append(f"{100.0 - place_one - rest * 6:.2f}%")
    return {
        "hero": name or f"Герой {idx}",
        "dbfId": 50_000 + idx,
        "pick_rate": f"{10 + idx / 10:.2f}%",
        "avg_placement": avg or f"{3.5 + idx / 100:.2f}",
        "tier": ["S", "A", "B", "C"][idx % 4],
        "placement_distribution": distribution,
    }


class SourceValidatorsTest(unittest.TestCase):
    def test_bg_heroes_semantic_validator_accepts_diverse_rows(self) -> None:
        structured = {
            "type": "bg_heroes",
            "heroes": [_hero_row(idx) for idx in range(40)],
        }

        report = validate_structured("hsreplay_battlegrounds_heroes", structured)

        self.assertTrue(report.ok)
        self.assertGreaterEqual(report.score, 0.95)
        self.assertEqual(report.metrics["valid_names"], 40)
        self.assertEqual(report.metrics["valid_distributions"], 40)

    def test_bg_heroes_semantic_validator_rejects_formally_filled_placeholders(self) -> None:
        structured = {
            "type": "bg_heroes",
            "heroes": [_hero_row(idx, name="—", avg="7") for idx in range(40)],
        }

        report = validate_structured("hsreplay_battlegrounds_heroes", structured)

        self.assertFalse(report.ok)
        codes = {issue.code for issue in report.issues}
        self.assertIn("bg_heroes.bad_names", codes)
        self.assertIn("bg_heroes.low_avg_diversity", codes)

    def test_quality_validation_runs_semantic_validator(self) -> None:
        source = SOURCE_BY_ID["hsreplay_battlegrounds_heroes"]
        parsed = {
            "title": "HSReplay premium Battlegrounds heroes tier list.",
            "structured": {
                "type": "bg_heroes",
                "heroes": [
                    {
                        **_hero_row(idx, avg="7"),
                        "hero": f"Герой {idx}",
                    }
                    for idx in range(40)
                ],
            },
        }

        ok, reason = validate_parsed_data(source, parsed)

        self.assertFalse(ok)
        self.assertIn("source semantic validation failed", reason)
        self.assertIn("avg_placement diversity", reason)


if __name__ == "__main__":
    unittest.main()
