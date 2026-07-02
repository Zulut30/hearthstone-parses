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

    def test_arena_class_matrix_with_empty_matchups_is_non_blocking(self) -> None:
        # Dual-class arena was permanently removed from the game, so the
        # "directed pairs" schema was retired: arena_class_matrix is NOT in the
        # _VALIDATORS registry (app/structured_schema.py:124-133) and empty
        # matchups are the normal upstream shape; validation of this type lives
        # in the quality gate (app/scrapers/quality.py:267-276), which accepts
        # empty matchups.
        result = validate_structured_schema(
            {
                "type": "arena_class_matrix",
                "classes": [
                    {"class": "Deathknight", "deck_class": 1, "win_rate": 50.0},
                    {"class": "Druid", "deck_class": 2, "win_rate": 51.0},
                    {"class": "Demonhunter", "deck_class": 14, "win_rate": 52.0},
                ],
                "matchups": [],
            }
        )

        self.assertEqual(
            result,
            {
                "ok": True,
                "type": "arena_class_matrix",
                "validated": False,
                "reason": "no schema registered",
            },
        )

    def test_arena_class_matrix_tolerates_legacy_matchup_rows(self) -> None:
        # Legacy payloads with dual-class matchup rows (including aggregate rows
        # with class_b=None) must not raise: with no schema registered for
        # arena_class_matrix (app/structured_schema.py:137-142) the validator is
        # intentionally non-blocking for this type.
        result = validate_structured_schema(
            {
                "type": "arena_class_matrix",
                "classes": [
                    {"class": "Deathknight", "deck_class": 1, "win_rate": 50.0},
                    {"class": "Druid", "deck_class": 2, "win_rate": 51.0},
                ],
                "matchups": [
                    {"class_a": "Deathknight", "class_b": "Druid", "deck_class": 1, "secondary_deck_class": 2, "win_rate": 53.0},
                    {"class_a": "Druid", "class_b": "Deathknight", "deck_class": 2, "secondary_deck_class": 1, "win_rate": 47.0},
                    {"class_a": "Deathknight", "class_b": None, "deck_class": 1, "secondary_deck_class": None, "win_rate": 50.0},
                ],
            }
        )

        self.assertTrue(result["ok"])
        self.assertFalse(result["validated"])
        self.assertEqual(result["reason"], "no schema registered")

    def test_unknown_schema_is_non_blocking(self) -> None:
        result = validate_structured_schema({"type": "legacy_dataset", "rows": []})

        self.assertTrue(result["ok"])
        self.assertFalse(result["validated"])


if __name__ == "__main__":
    unittest.main()
