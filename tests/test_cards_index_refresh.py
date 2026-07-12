from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from app import cards_index


@pytest.fixture(autouse=True)
def reset_cards_index(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cards_index, "CACHE_PATH_EN", tmp_path / "cards.enUS.json")
    monkeypatch.setattr(cards_index, "CACHE_PATH_RU", tmp_path / "cards.ruRU.json")
    monkeypatch.setattr(cards_index, "MIN_CARD_COUNT", 1)
    for name in ("_cache_en", "_cache_ru", "_by_dbf", "_by_id", "_by_id_ru", "_by_name_en", "_by_name_ru"):
        monkeypatch.setattr(cards_index, name, None)


def _response(cards: list[dict]) -> Mock:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = cards
    return response


def test_in_memory_index_refreshes_after_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    first = [{"id": "OLD", "dbfId": 1, "name": "Old Card"}]
    second = [{"id": "NEW", "dbfId": 2, "name": "New Card"}]
    clock = Mock(return_value=100.0)
    get = Mock(side_effect=[_response(first), _response(second)])
    monkeypatch.setattr(cards_index.time, "time", clock)
    monkeypatch.setattr(cards_index.httpx, "get", get)

    assert set(cards_index.cards_by_id()) == {"OLD"}
    clock.return_value = 100.0 + cards_index.CACHE_TTL_SECONDS + 1
    assert set(cards_index.cards_by_id()) == {"NEW"}
    assert get.call_count == 2


def test_stale_cache_survives_network_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    stale = {"fetched_at": 1.0, "cards": [{"id": "SAFE", "dbfId": 7, "name": "Safe Card"}]}
    cards_index.CACHE_PATH_EN.write_text(json.dumps(stale), encoding="utf-8")
    monkeypatch.setattr(cards_index.time, "time", lambda: cards_index.CACHE_TTL_SECONDS + 10.0)
    get = Mock(side_effect=RuntimeError("offline"))
    monkeypatch.setattr(cards_index.httpx, "get", get)

    assert set(cards_index.cards_by_id()) == {"SAFE"}
    assert set(cards_index.cards_by_id()) == {"SAFE"}
    assert get.call_count == 1


def test_truncated_refresh_does_not_replace_complete_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    old_cards = [
        {"id": f"OLD_{index}", "dbfId": index, "name": f"Old {index}"}
        for index in range(10)
    ]
    stale = {"fetched_at": 1.0, "cards": old_cards}
    cards_index.CACHE_PATH_EN.write_text(json.dumps(stale), encoding="utf-8")
    monkeypatch.setattr(cards_index.time, "time", lambda: cards_index.CACHE_TTL_SECONDS + 10.0)
    monkeypatch.setattr(cards_index.httpx, "get", Mock(return_value=_response(old_cards[:2])))

    assert len(cards_index.cards_by_id()) == 10
    persisted = json.loads(cards_index.CACHE_PATH_EN.read_text(encoding="utf-8"))
    assert len(persisted["cards"]) == 10


def test_card_from_id_uses_locale_id_instead_of_translated_name_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    english = [{"id": "CARD_1", "dbfId": 1, "name": "Arcane Test"}]
    russian = [{"id": "CARD_1", "dbfId": 1, "name": "Тайное испытание"}]
    monkeypatch.setattr(
        cards_index.httpx,
        "get",
        Mock(side_effect=[_response(russian), _response(english)]),
    )

    localized = cards_index.card_from_id("CARD_1", locale="ruRU")

    assert localized["name"] == "Тайное испытание"
