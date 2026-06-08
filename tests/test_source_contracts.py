from __future__ import annotations

import unittest

from app.api_only_sources import blocks_browser_fallback
from app.dataset_regression import check_dataset_regression
from app.hsreplay_client import _channel_urls
from app.scrapers.quality import quality_metrics, validate_parsed_data
from app.source_contracts import contract_quality_report, get_contract
from app.sources import SOURCE_BY_ID


class SourceContractsTest(unittest.TestCase):
    def test_arena_advanced_contract_blocks_bad_fallback(self) -> None:
        contract = get_contract("hsreplay_arena_cards_advanced")

        self.assertIsNotNone(contract)
        self.assertFalse(contract.allow_browser_fallback)  # type: ignore[union-attr]
        self.assertTrue(blocks_browser_fallback("hsreplay_arena_cards_advanced"))

    def test_plan_named_sources_have_contracts(self) -> None:
        for source_id in (
            "hsreplay_arena_winning_decks",
            "hsreplay_arena_legendaries",
            "hsreplay_battlegrounds_trinkets_lesser",
            "hsreplay_battlegrounds_trinkets_greater",
        ):
            with self.subTest(source_id=source_id):
                self.assertIsNotNone(get_contract(source_id))

    def test_arena_winning_decks_contract_checks_final_deck_fill(self) -> None:
        report = contract_quality_report(
            "hsreplay_arena_winning_decks",
            {
                "type": "arena_winning_decks",
                "decks": [{"title": "good", "final_deck": ["Card"]}, {"title": "bad", "final_deck": []}],
            },
        )

        self.assertFalse(report["ok"])
        self.assertIn("final_deck", report["critical_fields"])

    def test_trinket_contract_checks_pick_rate_fill(self) -> None:
        report = contract_quality_report(
            "hsreplay_battlegrounds_trinkets_lesser",
            {
                "type": "bg_trinkets",
                "trinkets": [{"name": f"Trinket {idx}", "pick_rate": "10%"} for idx in range(8)],
            },
        )

        self.assertTrue(report["ok"])
        self.assertEqual(report["quality_score"], 1.0)

    def test_hsreplay_contract_overrides_channel_order(self) -> None:
        labels = [
            label
            for label, _ in _channel_urls(
                "https://hsreplay.net/api/v1/arena/card_stats/",
                source_id="hsreplay_arena_cards_advanced",
            )
        ]

        self.assertEqual(labels[:2], ["curl_cffi", "flaresolverr"])

    def test_contract_field_fill_rejects_missing_hidden_columns(self) -> None:
        source = SOURCE_BY_ID["hsreplay_arena_cards_advanced"]
        cards = [
            {
                "name": f"Card {idx}",
                "deck_winrate": "55%",
                "winrate_when_drawn": "56%",
                "winrate_when_played": "57%",
                "in_runs": "1%",
                "avg_copies": "1.1",
            }
            for idx in range(900)
        ]
        for card in cards[:200]:
            card.pop("winrate_when_drawn")
        parsed = {
            "title": "HSReplay Arena",
            "structured": {"type": "arena_card_tiers", "cards": cards},
            "text_preview": ["arena"] * 50,
        }

        ok, reason = validate_parsed_data(source, parsed)

        self.assertFalse(ok)
        self.assertIn("winrate_when_drawn fill rate", reason)

    def test_quality_metrics_include_contract_report(self) -> None:
        source = SOURCE_BY_ID["hsreplay_cards_legend_1d"]
        parsed = {
            "structured": {
                "type": "card_stats",
                "cards": [{"id": idx, "deck_winrate": "55%", "deck_popularity": "1%"} for idx in range(900)],
            }
        }

        metrics = quality_metrics(source, parsed)

        self.assertEqual(metrics["rows_total"], 900)
        self.assertEqual(metrics["quality_score"], 1.0)
        self.assertIn("deck_winrate", metrics["critical_fields"])

    def test_daily_source_uses_contract_regression_ratio(self) -> None:
        source = SOURCE_BY_ID["hsreplay_cards_wild_legend_1d"]
        prev = {"structured": {"type": "card_stats", "cards": [{"id": idx} for idx in range(1000)]}}
        new = {"structured": {"type": "card_stats", "cards": [{"id": idx} for idx in range(520)]}}

        reg, _msg, extra = check_dataset_regression(source, previous_data=prev, new_data=new)

        self.assertFalse(reg)
        self.assertEqual(extra["drop_ratio"], 0.5)

    def test_contract_report_flags_too_few_rows(self) -> None:
        report = contract_quality_report(
            "hsreplay_meta_archetypes_legend_eu_1d",
            {"type": "hsreplay_meta_archetypes", "classes": []},
        )

        self.assertFalse(report["ok"])
        self.assertIn("too few rows", "; ".join(report["warnings"]))


if __name__ == "__main__":
    unittest.main()
