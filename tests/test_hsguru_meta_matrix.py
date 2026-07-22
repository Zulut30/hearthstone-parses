from __future__ import annotations

from datetime import UTC, datetime
import asyncio
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.main import app


client = TestClient(app)


HSGURU_TABLE = """
<html><body><table>
  <thead><tr>
    <th>Archetype</th><th>Winrate</th><th>Popularity</th>
    <th>Turns</th><th>Duration</th><th>Climbing Speed</th>
  </tr></thead>
  <tbody>
    <tr><td>Big Shaman</td><td>55.4%</td><td>1.7% (5,321)</td><td>8.2</td><td>7.6 min</td><td>+2.4</td></tr>
    <tr><td>Quest Mage</td><td>51.1%</td><td>0.8% (742)</td><td>9.1</td><td>8.0 min</td><td>+0.4</td></tr>
  </tbody>
</table></body></html>
"""


def test_matrix_has_120_remote_slices_and_six_local_min_game_filters() -> None:
    from app.hsguru_meta_matrix import MIN_GAMES, iter_slice_specs

    specs = list(iter_slice_specs())

    assert MIN_GAMES == (100, 250, 500, 1000, 2500, 5000)
    assert 7500 not in MIN_GAMES
    assert len(specs) == 120
    assert len({spec.key for spec in specs}) == 120
    assert all("min_games=100" in spec.url for spec in specs)
    assert all("7500" not in spec.url for spec in specs)
    assert {spec.period for spec in specs} == {
        "past_day",
        "past_3_days",
        "past_week",
        "past_2_weeks",
    }
    assert {spec.rank for spec in specs} == {
        "all", "legend", "diamond_4to1", "top_5k", "top_legend"
    }
    assert {spec.coin for spec in specs} == {"any_player", "going_first", "on_coin"}
    assert all(
        "player_has_coin=" not in spec.url
        for spec in specs
        if spec.coin == "any_player"
    )


def test_hsguru_table_parser_preserves_game_count_for_local_filtering() -> None:
    from app.hsguru_meta_matrix import parse_meta_rows

    rows = parse_meta_rows(HSGURU_TABLE)

    assert rows == [
        {
            "archetype": "Big Shaman",
            "winrate": 55.4,
            "popularity": 1.7,
            "games": 5321,
            "turns": 8.2,
            "duration_minutes": 7.6,
            "climbing_speed": 2.4,
        },
        {
            "archetype": "Quest Mage",
            "winrate": 51.1,
            "popularity": 0.8,
            "games": 742,
            "turns": 9.1,
            "duration_minutes": 8.0,
            "climbing_speed": 0.4,
        },
    ]


def test_hsguru_table_parser_maps_statistics_by_header_not_column_position() -> None:
    from app.hsguru_meta_matrix import parse_meta_rows

    reordered = """
    <table><thead><tr>
      <th>Popularity</th><th>Archetype</th><th>Climbing Speed</th>
      <th>Duration</th><th>Winrate↓</th><th>Turns</th>
    </tr></thead><tbody><tr>
      <td>1.7% (5,321)</td><td>Big Shaman</td><td>+2.4⭐/h</td>
      <td>7.6 min</td><td>55.4</td><td>8.2</td>
    </tr></tbody></table>
    """

    assert parse_meta_rows(reordered) == [{
        "archetype": "Big Shaman",
        "winrate": 55.4,
        "popularity": 1.7,
        "games": 5321,
        "turns": 8.2,
        "duration_minutes": 7.6,
        "climbing_speed": 2.4,
    }]


def test_hsguru_table_parser_rejects_incomplete_statistics() -> None:
    from app.hsguru_meta_matrix import parse_meta_rows

    broken = HSGURU_TABLE.replace("<td>55.4%</td>", "<td>—</td>", 1)

    with pytest.raises(ValueError, match="invalid statistics"):
        parse_meta_rows(broken)


def test_refresh_publishes_one_unified_dataset_after_120_firecrawl_pages() -> None:
    from app.firecrawl_backend import FirecrawlScrape
    from app.hsguru_meta_matrix import refresh_hsguru_meta_matrix

    calls: list[str] = []

    async def scrape(spec):
        calls.append(spec.url)
        return FirecrawlScrape(
            html=HSGURU_TABLE,
            markdown="",
            screenshot=None,
            metadata={"creditsUsed": 1},
            status_code=200,
            final_url=spec.url,
        )

    with (
        patch("app.hsguru_meta_matrix.load_dataset", return_value=None),
        patch("app.hsguru_meta_matrix.save_dataset") as save_dataset,
        patch("app.hsguru_meta_matrix.save_status") as save_status,
    ):
        result = asyncio.run(
            refresh_hsguru_meta_matrix(concurrency=5, attempts=1, scrape=scrape)
        )

    assert result["ok"] is True
    assert result["base_slices"] == 120
    assert result["logical_slices"] == 720
    assert result["firecrawl_credits_used"] == 120
    assert len(calls) == 120
    save_dataset.assert_called_once()
    dataset = save_dataset.call_args.args[1]
    assert dataset["data"]["structured"]["dimensions"]["min_games"] == [
        100, 250, 500, 1000, 2500, 5000
    ]
    save_status.assert_called_once()


def test_v1_hsguru_meta_filters_unified_dataset_by_min_games() -> None:
    fetched_at = datetime.now(UTC).isoformat()
    dataset = {
        "source_id": "hsguru_meta_matrix",
        "fetched_at": fetched_at,
        "backend": "firecrawl",
        "data": {
            "structured": {
                "type": "hsguru_meta_matrix",
                "schema_version": 1,
                "dimensions": {
                    "formats": ["standard", "wild"],
                    "ranks": ["all", "legend", "diamond_4to1", "top_5k", "top_legend"],
                    "periods": ["past_day", "past_3_days", "past_week", "past_2_weeks"],
                    "coins": ["any_player", "going_first", "on_coin"],
                    "min_games": [100, 250, 500, 1000, 2500, 5000],
                },
                "slices": [
                    {
                        "key": "standard|legend|past_day|going_first",
                        "format": "standard",
                        "rank": "legend",
                        "period": "past_day",
                        "coin": "going_first",
                        "source_url": "https://www.hsguru.com/meta?format=2&rank=legend&period=past_day&player_has_coin=no&min_games=100",
                        "rows": [
                            {"archetype": "Big Shaman", "games": 5321, "winrate": 55.4},
                            {"archetype": "Quest Mage", "games": 742, "winrate": 51.1},
                        ],
                    }
                ],
            }
        },
    }

    with patch("app.routers.hsguru_meta.load_dataset", return_value=dataset):
        response = client.get(
            "/v1/hsguru/meta?format=standard&rank=legend&period=past_day&coin=going_first&min_games=2500"
        )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["items"] == [
        {"archetype": "Big Shaman", "games": 5321, "winrate": 55.4}
    ]
    assert body["data"]["min_games"] == 2500
    assert body["meta"]["source_id"] == "hsguru_meta_matrix"
    assert body["meta"]["count"] == 1


def test_v1_hsguru_meta_rejects_removed_min_games_value() -> None:
    response = client.get(
        "/v1/hsguru/meta?format=standard&rank=legend&period=past_day&coin=going_first&min_games=7500"
    )

    assert response.status_code == 422


def test_v1_hsguru_meta_accepts_all_ranks_and_any_player() -> None:
    fetched_at = datetime.now(UTC).isoformat()
    dataset = {
        "source_id": "hsguru_meta_matrix",
        "fetched_at": fetched_at,
        "data": {"structured": {"slices": [{
            "key": "standard|all|past_day|any_player",
            "source_url": "https://www.hsguru.com/meta?format=2&rank=all&period=past_day&min_games=100",
            "rows": [{"archetype": "Big Shaman", "games": 5321, "winrate": 55.4}],
        }]}},
    }

    with patch("app.routers.hsguru_meta.load_dataset", return_value=dataset):
        response = client.get(
            "/v1/hsguru/meta?format=standard&rank=all&period=past_day&coin=any_player&min_games=100"
        )

    assert response.status_code == 200
    assert response.json()["data"]["rank"] == "all"
    assert response.json()["data"]["coin"] == "any_player"
