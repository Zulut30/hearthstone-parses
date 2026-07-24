from __future__ import annotations

from unittest.mock import patch

from bs4 import BeautifulSoup

from app.fetcher import _enrich_firecrawl_trinkets_from_cache
from app.hsreplay_extract import (
    extract_bg_trinkets,
    extract_for_source,
    infer_minimum_games,
    parse_bg_trinkets_api_payload,
)
from app.parser import parse_html
from app.sources import Source
from app.structured import enrich_trinket_variant_fields, parse_bg_trinkets
from app.trinket_slices import source_ids_for_trinket_slice


def test_parse_bg_trinkets_keeps_compass_tribe_variants() -> None:
    lines = [
        "Tier",
        "Trinket",
        "Pick Rate",
        "Avg. Placement",
        "Placement Distribution",
        "a",
        "2",
        "Colorful Compass",
        "Murloc",
        "Get a random 92. At the start of each turn, get another.",
        "32.1%",
        "3.87",
        "2",
        "Colorful Compass",
        "Undead",
        "Get a random 92. At the start of each turn, get another.",
        "24.2%",
        "3.88",
    ]

    trinkets = parse_bg_trinkets(lines)

    assert len(trinkets) == 2
    assert {row["tribe"] for row in trinkets} == {"Murloc", "Undead"}
    assert {row["tier"] for row in trinkets} == {"A"}
    assert all(row["cost"] == 2 for row in trinkets)


def test_extract_bg_trinkets_reads_hsreplay_variant_badges() -> None:
    html = """
    <div>
      <div><div>s</div></div>
      <div>
        <div>
          <div tabindex="0">
            <img src="https://art.hearthstonejson.com/v1/256x/BG30_MagicItem_426.webp">
            <div>
              <div><div><img alt="BG30_MagicItem_426" src="x"><div>2</div></div></div>
              <div>Colorful Compass
                <div>Murloc</div>
                <div><div>Get a random 92. At the start of each turn, get another.</div></div>
              </div>
            </div>
            <div>32.1%</div><div><div><div>3.87</div></div></div>
          </div>
          <div tabindex="0">
            <img src="https://art.hearthstonejson.com/v1/256x/BG30_MagicItem_426.webp">
            <div>
              <div><div><img alt="BG30_MagicItem_426" src="x"><div>2</div></div></div>
              <div>Colorful Compass
                <div>Undead</div>
                <div><div>Get a random 92. At the start of each turn, get another.</div></div>
              </div>
            </div>
            <div>24.2%</div><div><div><div>3.88</div></div></div>
          </div>
        </div>
      </div>
    </div>
    """

    trinkets = extract_bg_trinkets(BeautifulSoup(html, "lxml"))

    assert len(trinkets) == 2
    assert {row["tribe"] for row in trinkets} == {"Murloc", "Undead"}
    assert {row["trinket_id"] for row in trinkets} == {"BG30_MagicItem_426"}
    assert all(row["variant_key"] for row in trinkets)


def test_trinket_extractor_reports_fallback_level_and_dropped_rows() -> None:
    html = """
    <img alt="BG30_MagicItem_broken">
    <a href="/battlegrounds/trinkets/123/valid-trinket">Valid Trinket</a>
    """
    soup = BeautifulSoup(html, "lxml")

    structured = extract_for_source(
        "hsreplay_battlegrounds_trinkets_lesser",
        soup,
        html,
    )

    assert structured["parser_level"] == "fallback_anchor"
    assert structured["dropped_rows"] == 1
    assert [row["name"] for row in structured["trinkets"]] == ["Valid Trinket"]


def test_fallback_trinket_uses_canonical_identity_and_deduplicates_primary() -> None:
    html = """
    <div tabindex="0">
      <img alt="BG_TEST_001"><div>2</div><div>Test Trinket</div>
      <div>Stable description.</div><div>1.0%</div><div>4.0</div>
    </div>
    <a href="/battlegrounds/trinkets/123/test-trinket">Test Trinket</a>
    """
    with patch(
        "app.hsreplay_extract.cards_by_dbfid",
        return_value={123: {"dbfId": 123, "id": "BG_TEST_001", "name": "Test Trinket"}},
    ):
        structured = extract_for_source(
            "hsreplay_battlegrounds_trinkets_lesser",
            BeautifulSoup(html, "lxml"),
            html,
        )

    assert len(structured["trinkets"]) == 1
    assert structured["trinkets"][0]["trinket_id"] == "BG_TEST_001"


def test_enrich_trinket_uses_full_canonical_text_without_overwriting_live_stats() -> None:
    row = {
        "trinket_id": "BG_TEST_002",
        "name": "Ironforge Anvil",
        "description": "Start of Combat:",
        "cost": 4,
        "tier": "S",
        "pick_rate": "12.3%",
        "avg_placement": "3.45",
    }
    cards = {
        "enUS": {
            "BG_TEST_002": {
                "id": "BG_TEST_002",
                "name": "Ironforge Anvil",
                "text": "<b>Start of Combat:</b> Triple the stats of your minions with no type.",
                "cost": 99,
            }
        },
        "ruRU": {
            "BG_TEST_002": {
                "id": "BG_TEST_002",
                "name": "Стальгорнская наковальня",
                "text": "<b>Начало боя:</b> утраивает характеристики ваших существ без типа.",
                "cost": 99,
            }
        },
    }

    with patch("app.structured.cards_by_id", side_effect=lambda locale="enUS": cards[locale]):
        enriched = enrich_trinket_variant_fields(row, trinket_type="Lesser")

    assert enriched["description"] == (
        "Start of Combat: Triple the stats of your minions with no type."
    )
    assert enriched["localized_name"] == "Стальгорнская наковальня"
    assert enriched["localized_description"] == (
        "Начало боя: утраивает характеристики ваших существ без типа."
    )
    assert enriched["cost"] == 4
    assert enriched["tier"] == "S"
    assert enriched["pick_rate"] == "12.3%"
    assert enriched["avg_placement"] == "3.45"


def test_enrich_trinket_replaces_dynamic_tribe_placeholder() -> None:
    cards = {
        "enUS": {
            "BG_TEST_003": {
                "id": "BG_TEST_003",
                "name": "Colorful Compass",
                "text": "[x]Get 2 random 92.\nAt the start of each turn, get 2 more.",
            }
        },
        "ruRU": {
            "BG_TEST_003": {
                "id": "BG_TEST_003",
                "name": "Разноцветный компас",
                "text": (
                    "Вы получаете 2 случайные карты типа «92». "
                    "После того как вы разыгрываете 7 "
                    "|4(существо,существа,существ), эффект повторяется, "
                    "и вы получаете (1) |4(золотой,золотых,золотых)."
                ),
            }
        },
    }

    with patch("app.structured.cards_by_id", side_effect=lambda locale="enUS": cards[locale]):
        enriched = enrich_trinket_variant_fields(
            {
                "trinket_id": "BG_TEST_003",
                "name": "Colorful Compass",
                "description": "Get a random 92.",
                "tribe": "Murloc",
            },
            trinket_type="Lesser",
        )

    assert enriched["description"] == (
        "Get 2 random Murlocs. At the start of each turn, get 2 more."
    )
    assert "92" not in enriched["localized_description"]
    assert "мурлок" in enriched["localized_description"].lower()
    assert "|4(" not in enriched["localized_description"]
    assert "7 существ" in enriched["localized_description"]
    assert "1 золотой" in enriched["localized_description"]


def test_parse_bg_trinkets_api_payload_keeps_top_one_percent_metrics_and_variants() -> None:
    payload = [
        {
            "trinket_dbf_id": 111488,
            "extra_data": None,
            "pick_rate": 28.1,
            "avg_final_placement": 2.75,
            "final_placement_distribution": [42.0, 18.0, 11.0, 9.0, 8.0, 5.0, 4.0, 3.0],
            "tier": "s",
            "group": "greater",
        },
        {
            "trinket_dbf_id": 112002,
            "extra_data": 14,
            "pick_rate": 31.2,
            "avg_final_placement": 3.4,
            "final_placement_distribution": [20.0] * 8,
            "tier": "a",
            "group": "greater",
        },
        {
            "trinket_dbf_id": 999999,
            "extra_data": None,
            "pick_rate": 99.9,
            "avg_final_placement": 1.0,
            "final_placement_distribution": [100.0] + [0.0] * 7,
            "tier": "s",
            "group": "lesser",
        },
    ]
    cards = {
        111488: {
            "dbfId": 111488,
            "id": "BG30_MagicItem_403",
            "name": "Ironforge Anvil",
            "cost": 4,
        },
        112002: {
            "dbfId": 112002,
            "id": "BG30_MagicItem_426",
            "name": "Colorful Compass",
            "cost": 2,
        },
    }

    with (
        patch("app.hsreplay_extract.cards_by_dbfid", return_value=cards),
        patch("app.structured.cards_by_id", return_value={}),
    ):
        trinkets = parse_bg_trinkets_api_payload(payload, trinket_type="Greater")

    assert len(trinkets) == 2
    anvil = next(row for row in trinkets if row["trinket_id"] == "BG30_MagicItem_403")
    compass = next(row for row in trinkets if row["trinket_id"] == "BG30_MagicItem_426")
    assert anvil["pick_rate"] == "28.1%"
    assert anvil["avg_placement"] == "2.75"
    assert anvil["tier"] == "S"
    assert anvil["cost"] == 4
    assert anvil["placement_distribution"][0] == {"place": 1, "rate": "42.00%"}
    assert compass["tribe"] == "Murloc"


def test_trinket_distribution_exposes_minimum_consistent_game_sample() -> None:
    distribution = [26.27, 11.02, 13.56, 10.17, 6.78, 7.63, 16.10, 8.47]

    assert infer_minimum_games(distribution) == 118


def test_trinket_slice_maps_default_and_filtered_datasets() -> None:
    assert source_ids_for_trinket_slice("TOP_1_PERCENT", "LAST_7_DAYS") == (
        "hsreplay_battlegrounds_trinkets_lesser",
        "hsreplay_battlegrounds_trinkets_greater",
    )
    assert source_ids_for_trinket_slice("TOP_20_PERCENT", "CURRENT_BATTLEGROUNDS_PATCH") == (
        "hsreplay_battlegrounds_trinkets_top_20_percent_current_battlegrounds_patch",
    )


def test_parse_html_recognizes_combined_mmr_and_period_trinket_slice() -> None:
    source = Source(
        "hsreplay_battlegrounds_trinkets_top_20_percent_current_battlegrounds_patch",
        "https://hsreplay.net/api/v1/battlegrounds/trinkets/"
        "?BattlegroundsMMRPercentile=TOP_20_PERCENT"
        "&BattlegroundsTimeRange=CURRENT_BATTLEGROUNDS_PATCH",
        "hsreplay",
        "battlegrounds",
    )
    html = """
    <html><body><pre>[
      {
        "trinket_dbf_id": 111488,
        "extra_data": null,
        "pick_rate": 28.1,
        "avg_final_placement": 2.75,
        "final_placement_distribution": [26.27, 11.02, 13.56, 10.17, 6.78, 7.63, 16.1, 8.47],
        "tier": "s",
        "group": "greater"
      },
      {
        "trinket_dbf_id": 112002,
        "extra_data": 14,
        "pick_rate": 31.2,
        "avg_final_placement": 3.4,
        "final_placement_distribution": [20, 15, 15, 15, 10, 10, 10, 5],
        "tier": "a",
        "group": "lesser"
      }
    ]</pre></body></html>
    """
    cards = {
        111488: {
            "dbfId": 111488,
            "id": "BG30_MagicItem_403",
            "name": "Ironforge Anvil",
            "cost": 4,
        },
        112002: {
            "dbfId": 112002,
            "id": "BG30_MagicItem_426",
            "name": "Colorful Compass",
            "cost": 2,
        },
    }

    with (
        patch("app.hsreplay_extract.cards_by_dbfid", return_value=cards),
        patch("app.structured.cards_by_id", return_value={}),
    ):
        parsed = parse_html(source, html)

    rows = parsed["structured"]["trinkets"]
    assert {row["trinket_tier"] for row in rows} == {"Lesser", "Greater"}
    assert parsed["structured"]["source"]["mmr_percentile"] == "TOP_20_PERCENT"
    assert parsed["structured"]["source"]["time_range"] == "CURRENT_BATTLEGROUNDS_PATCH"
    anvil = next(row for row in rows if row["trinket_id"] == "BG30_MagicItem_403")
    assert anvil["games"] == 118
    assert anvil["games_is_minimum"] is True


def test_parse_html_recognizes_hsreplay_trinket_json_api() -> None:
    source = Source(
        "hsreplay_battlegrounds_trinkets_greater",
        "https://hsreplay.net/api/v1/battlegrounds/trinkets/"
        "?BattlegroundsMMRPercentile=TOP_1_PERCENT",
        "hsreplay",
        "battlegrounds",
    )
    html = """
    <html><body><pre>[
      {
        "trinket_dbf_id": 111488,
        "extra_data": null,
        "pick_rate": 28.1,
        "avg_final_placement": 2.75,
        "final_placement_distribution": [42, 18, 11, 9, 8, 5, 4, 3],
        "tier": "s",
        "group": "greater"
      }
    ]</pre></body></html>
    """
    cards = {
        111488: {
            "dbfId": 111488,
            "id": "BG30_MagicItem_403",
            "name": "Ironforge Anvil",
            "cost": 4,
        }
    }

    with (
        patch("app.hsreplay_extract.cards_by_dbfid", return_value=cards),
        patch("app.structured.cards_by_id", return_value={}),
    ):
        parsed = parse_html(source, html)

    rows = parsed["structured"]["trinkets"]
    assert len(rows) == 1
    assert rows[0]["trinket_id"] == "BG30_MagicItem_403"
    assert rows[0]["avg_placement"] == "2.75"


def test_firecrawl_json_api_does_not_reintroduce_stale_trinket_rows() -> None:
    source = Source(
        "hsreplay_battlegrounds_trinkets_greater",
        "https://hsreplay.net/api/v1/battlegrounds/trinkets/",
        "hsreplay",
        "battlegrounds",
    )
    current = {
        "structured": {
            "type": "bg_trinkets",
            "source": {"backend": "hsreplay_json_api"},
            "trinkets": [
                {
                    "name": "Current Trinket",
                    "trinket_id": "BG_CURRENT",
                    "pick_rate": "20.0%",
                    "avg_placement": "3.00",
                }
            ],
        }
    }
    previous = {
        "data": {
            "structured": {
                "type": "bg_trinkets",
                "trinkets": [
                    {
                        "name": "Current Trinket",
                        "trinket_id": "BG_CURRENT",
                        "pick_rate": "10.0%",
                        "avg_placement": "4.00",
                    },
                    {
                        "name": "Removed Trinket",
                        "trinket_id": "BG_STALE",
                        "pick_rate": "99.0%",
                        "avg_placement": "1.00",
                    },
                ],
            }
        }
    }

    with (
        patch("app.fetcher.load_dataset", return_value=previous),
        patch("app.structured.cards_by_id", return_value={}),
    ):
        enriched = _enrich_firecrawl_trinkets_from_cache(source, current)

    rows = enriched["structured"]["trinkets"]
    assert [row["trinket_id"] for row in rows] == ["BG_CURRENT"]
