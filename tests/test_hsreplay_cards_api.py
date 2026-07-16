from __future__ import annotations

import unittest

from app.hsreplay_cards_api import parse_cards_from_api_payloads


class HsReplayCardsApiTests(unittest.TestCase):
    def test_merges_separate_metric_series_for_the_same_card(self) -> None:
        cards = parse_cards_from_api_payloads(
            [
                (
                    "https://hsreplay.net/analytics/query/card_list/",
                    {
                        "render_as": "card_list",
                        "series": {
                            "data": {
                                "winrate": [
                                    {
                                        "dbf_id": 69545,
                                        "included_winrate": 100.0,
                                    }
                                ],
                                "popularity": [
                                    {
                                        "dbf_id": 69545,
                                        "included_popularity": 0.25,
                                        "times_played": 10,
                                    }
                                ],
                            }
                        },
                    },
                )
            ],
            sort_mode="popularity",
        )

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["deck_popularity"], "0.25%")
        self.assertEqual(cards[0]["deck_winrate"], "100.00%")
        self.assertEqual(cards[0]["times_played"], 10)

    def test_does_not_use_winrate_as_deck_popularity(self) -> None:
        cards = parse_cards_from_api_payloads(
            [
                (
                    "https://hsreplay.net/analytics/query/card_list/",
                    {
                        "series": {
                            "data": {
                                "winrate": [
                                    {
                                        "dbf_id": 69545,
                                        "included_winrate": 100.0,
                                    }
                                ]
                            }
                        }
                    },
                )
            ],
            sort_mode="popularity",
        )

        self.assertEqual(cards[0]["deck_winrate"], "100.00%")
        self.assertNotIn("deck_popularity", cards[0])


if __name__ == "__main__":
    unittest.main()
