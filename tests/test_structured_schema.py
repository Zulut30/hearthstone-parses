from __future__ import annotations

import unittest

from app.structured_schema import StructuredSchemaError, validate_structured_schema


class StructuredSchemaTest(unittest.TestCase):
    def test_validates_card_stats_schema(self) -> None:
        result = validate_structured_schema(
            {
                "type": "card_stats",
                "cards": [{"id": 1, "deck_winrate": "51.00%"}],
            }
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["validated"])

    def test_rejects_card_stats_without_any_metrics(self) -> None:
        with self.assertRaisesRegex(StructuredSchemaError, "missing all card metrics"):
            validate_structured_schema({"type": "card_stats", "cards": [{"id": 1}]})

    def test_allows_late_card_rows_without_metrics_when_dataset_has_metrics(self) -> None:
        cards = [{"id": idx, "deck_winrate": "51.00%"} for idx in range(50)]
        cards.append({"id": 51})

        result = validate_structured_schema({"type": "card_stats", "cards": cards})

        self.assertTrue(result["validated"])

    def test_rejects_invalid_rows_after_first_fifty(self) -> None:
        cards = [{"id": idx, "deck_winrate": "51.00%"} for idx in range(50)]
        cards.append({"deck_winrate": "51.00%"})

        with self.assertRaisesRegex(StructuredSchemaError, "cards\\[50\\].*missing id/dbfId"):
            validate_structured_schema({"type": "card_stats", "cards": cards})

    def test_validates_hsreplay_meta_archetypes_schema(self) -> None:
        result = validate_structured_schema(
            {
                "type": "hsreplay_meta_archetypes",
                "classes": [
                    {
                        "class": "DRUID",
                        "archetypes": [
                            {
                                "archetype_id": 52,
                                "archetype": "Token Druid",
                                "winrate": "51.06%",
                                "popularity": "6.55%",
                                "games": 1269,
                            }
                        ],
                    }
                ],
            }
        )

        self.assertTrue(result["validated"])

    def test_allows_partial_bg_metric_values_when_keys_are_present(self) -> None:
        minions = validate_structured_schema(
            {"type": "bg_minions", "minions": [{"minion": "Test Minion", "impact": None}]}
        )
        compositions = validate_structured_schema(
            {
                "type": "bg_compositions",
                "compositions": [
                    {"type": "Beasts", "avg_placement": None, "placement_distribution": []}
                ],
            }
        )

        self.assertTrue(minions["validated"])
        self.assertTrue(compositions["validated"])

    def test_unknown_schema_is_non_blocking(self) -> None:
        result = validate_structured_schema({"type": "legacy_dataset", "rows": []})

        self.assertTrue(result["ok"])
        self.assertFalse(result["validated"])


if __name__ == "__main__":
    unittest.main()
