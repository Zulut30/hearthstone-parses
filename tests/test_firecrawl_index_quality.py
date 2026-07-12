from __future__ import annotations

from unittest.mock import patch

import pytest

from app.firecrawl_map import _validate_map_size, build_hsreplay_index


def _datasets() -> dict[str, dict]:
    return {
        "hsreplay_cards_legend_1d": {
            "cards": [
                {"id": f"C{idx}", "dbfId": idx, "name": f"Card {idx}", "type": "MINION"}
                for idx in range(120)
            ]
        },
        "hsreplay_battlegrounds_minions": {
            "minions": [
                {"id": f"BG{idx}", "dbfId": 10_000 + idx, "name": f"BG {idx}"}
                for idx in range(160)
            ]
        },
        "hsreplay_battlegrounds_heroes": {
            "heroes": [
                {"hero": f"Hero {idx}", "dbfId": 20_000 + idx}
                for idx in range(40)
            ]
        },
        "hsreplay_meta_archetypes_legend_eu_1d": {
            "classes": [
                {
                    "class": "MAGE",
                    "archetypes": [
                        {
                            "archetype": f"Deck {idx}",
                            "archetype_id": idx,
                            "url": f"https://hsreplay.net/archetypes/{idx}/deck-{idx}",
                        }
                        for idx in range(25)
                    ],
                }
            ]
        },
    }


def test_map_truncation_guard_rejects_collapsed_response() -> None:
    with pytest.raises(RuntimeError, match="truncation guard"):
        _validate_map_size(400, previous_count=3_800)


def test_map_truncation_guard_accepts_stable_response() -> None:
    _validate_map_size(3_700, previous_count=3_800)


def test_derived_index_is_written_only_when_all_inputs_are_complete() -> None:
    datasets = _datasets()

    with (
        patch("app.firecrawl_map._structured", side_effect=lambda source_id: datasets[source_id]),
        patch("app.firecrawl_map.load_hsreplay_map", return_value={"fetched_at": "now", "url_count": 3000}),
        patch("app.firecrawl_map._write_json") as write_json,
    ):
        result = build_hsreplay_index()

    assert result["counts"]["standard_unique_archetypes"] == 25
    write_json.assert_called_once()


def test_derived_index_preserves_previous_file_when_one_input_collapses() -> None:
    datasets = _datasets()
    datasets["hsreplay_battlegrounds_minions"] = {"minions": []}

    with (
        patch("app.firecrawl_map._structured", side_effect=lambda source_id: datasets[source_id]),
        patch("app.firecrawl_map.load_hsreplay_map", return_value={"fetched_at": "now", "url_count": 3000}),
        patch("app.firecrawl_map._write_json") as write_json,
        pytest.raises(RuntimeError, match="battlegrounds_minions too small"),
    ):
        build_hsreplay_index()

    write_json.assert_not_called()
