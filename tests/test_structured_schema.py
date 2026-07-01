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

    def test_validates_arena_class_matrix_directed_pairs(self) -> None:
        result = validate_structured_schema(
            {
                "type": "arena_class_matrix",
                "classes": [
                    {"class": "Death Knight", "deck_class": 1, "win_rate": 50.0},
                    {"class": "Druid", "deck_class": 2, "win_rate": 51.0},
                    {"class": "Demon Hunter", "deck_class": 14, "win_rate": 52.0},
                ],
                "matchups": [
                    {"class_a": "Death Knight", "class_b": "Druid", "deck_class": 1, "secondary_deck_class": 2, "win_rate": 53.0},
                    {"class_a": "Druid", "class_b": "Death Knight", "deck_class": 2, "secondary_deck_class": 1, "win_rate": 47.0},
                    {"class_a": "Death Knight", "class_b": "Demon Hunter", "deck_class": 1, "secondary_deck_class": 14, "win_rate": 45.0},
                    {"class_a": "Demon Hunter", "class_b": "Death Knight", "deck_class": 14, "secondary_deck_class": 1, "win_rate": 55.0},
                    {"class_a": "Druid", "class_b": "Demon Hunter", "deck_class": 2, "secondary_deck_class": 14, "win_rate": 54.0},
                    {"class_a": "Demon Hunter", "class_b": "Druid", "deck_class": 14, "secondary_deck_class": 2, "win_rate": 46.0},
                ],
            }
        )

        self.assertTrue(result["validated"])

    def test_rejects_arena_class_matrix_aggregate_rows(self) -> None:
        with self.assertRaisesRegex(StructuredSchemaError, "directed class pairs"):
            validate_structured_schema(
                {
                    "type": "arena_class_matrix",
                    "classes": [
                        {"class": "Death Knight", "deck_class": 1, "win_rate": 50.0},
                        {"class": "Druid", "deck_class": 2, "win_rate": 51.0},
                    ],
                    "matchups": [
                        {"class_a": "Death Knight", "class_b": "Druid", "deck_class": 1, "secondary_deck_class": 2, "win_rate": 53.0},
                        {"class_a": "Druid", "class_b": "Death Knight", "deck_class": 2, "secondary_deck_class": 1, "win_rate": 47.0},
                        {"class_a": "Death Knight", "class_b": None, "deck_class": 1, "secondary_deck_class": None, "win_rate": 50.0},
                    ],
                }
            )

    def test_unknown_schema_is_non_blocking(self) -> None:
        result = validate_structured_schema({"type": "legacy_dataset", "rows": []})

        self.assertTrue(result["ok"])
        self.assertFalse(result["validated"])


if __name__ == "__main__":
    unittest.main()
