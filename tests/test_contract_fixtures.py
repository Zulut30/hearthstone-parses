from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.hsreplay_bg_heroes import parse_hsreplay_bg_hero_stats_text
from app.hsreplay_cards_api import parse_cards_from_api_payloads
from app.hsreplay_meta_api import normalize_meta_archetypes
from app.vicious_live import build_ladder_view

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class ContractFixturesTest(unittest.TestCase):
    def test_hsreplay_card_list_contract_preserves_hidden_columns(self) -> None:
        payload = load_fixture("hsreplay_card_list.json")

        cards = parse_cards_from_api_payloads(
            [("https://hsreplay.net/analytics/query/card_list/", payload)],
            sort_mode="popularity",
        )

        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertEqual(card["dbfId"], 69545)
        self.assertEqual(card["deck_popularity"], "24.90%")
        self.assertEqual(card["deck_winrate"], "52.01%")
        self.assertEqual(card["winrate_when_drawn"], "53.50%")
        self.assertEqual(card["avg_turns_in_hand"], 0.75)
        self.assertEqual(card["avg_turn_played_on"], 4.53)

    def test_hsreplay_meta_archetypes_contract_groups_by_class(self) -> None:
        payload = load_fixture("hsreplay_meta_archetypes.json")

        classes = normalize_meta_archetypes(
            payload,
            {
                52: {"name": "Token Druid", "url": "/archetypes/52/token-druid"},
                142: {"name": "Burn Mage", "url": "/archetypes/142/burn-mage"},
            },
        )

        self.assertEqual(classes[0]["class"], "DRUID")
        self.assertEqual(classes[0]["games"], 1294)
        self.assertEqual(classes[0]["archetypes"][0]["archetype"], "Token Druid")
        self.assertEqual(classes[0]["archetypes"][0]["winrate"], "51.06%")
        self.assertEqual(classes[0]["archetypes"][0]["popularity"], "6.55%")

    def test_vicious_ladder_contract_builds_distributions(self) -> None:
        payload = load_fixture("vicious_ladder_data.json")

        view = build_ladder_view(payload["lastDay"])

        self.assertEqual(view["games"], 2000)
        self.assertEqual(view["class_distribution"][0]["class"], "DeathKnight")
        self.assertEqual(view["class_distribution"][0]["frequency"], "70.00%")
        self.assertEqual(view["deck_distribution"][0]["deck"], "Alpha DeathKnight")

    def test_hsreplay_bg_hero_stats_contract_preserves_distribution(self) -> None:
        payload = load_fixture("hsreplay_bg_hero_stats.json")

        stats = parse_hsreplay_bg_hero_stats_text(json.dumps(payload))

        self.assertEqual(stats[64400]["tier_v2"], "2")
        self.assertEqual(stats[64400]["api_avg_placement"], 4.42)
        self.assertEqual(len(stats[64400]["placement_distribution"]), 8)


if __name__ == "__main__":
    unittest.main()
