from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app import hsguru_decks
from app.firecrawl_backend import FirecrawlScrape
from app.hsguru_decks import parse_hsguru_decks_html


EVENLOCK_CODE = "AAEBAf0GBs30Av76A4f7A564BtvXB63ZBwycENfOA4j0A8b5A8f5A63pBdCeBu6hBom1BoSZB+C+B43cBwAA"
SECOND_EVENLOCK_CODE = "AAEBAf0GBM30Aof7A6nhBq3ZBw3XzgOI9APG+QPH+QP++gOt6QXQngbuoQaJtQacwQaEmQfb1weN3AcAAA=="


def _card(title: str, class_name: str, deck_code: str, games: int, winrate: float) -> str:
    return f"""
      <div id="deck_stats-42">
        <div class="decklist-info {class_name}">
          <button data-clipboard-text="### {title}\n# Format: Wild\n{deck_code}\n# You can view this deck at https://www.hsguru.com/deck/42\n"></button>
        </div>
        <span class="tag column"><span>{winrate}</span></span>
        <div>Games: {games}</div>
      </div>
    """


def test_parser_returns_only_the_exact_archetype_and_best_sample() -> None:
    html = (
        _card("Mug Shaman", "shaman", EVENLOCK_CODE, 9999, 70.0)
        + _card("Evenlock", "warlock", EVENLOCK_CODE, 4227, 61.1)
        + _card("Evenlock", "warlock", SECOND_EVENLOCK_CODE, 337, 68.5)
    )

    rows = parse_hsguru_decks_html(html, archetype="Evenlock", format_name="wild")

    assert len(rows) == 2
    assert rows[0]["archetype"] == "Evenlock"
    assert rows[0]["class"] == "Warlock"
    assert rows[0]["deck_code"] == EVENLOCK_CODE
    assert rows[0]["games"] == 4227


def test_parser_never_substitutes_another_archetype() -> None:
    html = _card("Mug Shaman", "shaman", EVENLOCK_CODE, 9999, 70.0)

    assert parse_hsguru_decks_html(html, archetype="Big Shaman", format_name="wild") == []


def test_exact_filtered_page_accepts_specific_build_title() -> None:
    html = _card("FUU Plague DK", "deathknight", EVENLOCK_CODE, 231, 50.0)

    rows = parse_hsguru_decks_html(
        html,
        archetype="Plague DK",
        format_name="wild",
        trust_exact_filter=True,
    )

    assert len(rows) == 1
    assert rows[0]["archetype"] == "Plague DK"
    assert rows[0]["title"] == "FUU Plague DK"
    assert rows[0]["class"] == "DeathKnight"


def test_lookup_continues_after_a_failed_fresh_slice() -> None:
    exact_row = {
        "archetype": "Big Shaman",
        "deck_code": EVENLOCK_CODE,
    }
    lookup = AsyncMock(side_effect=[RuntimeError("temporary upstream failure"), [exact_row]])

    with patch.object(hsguru_decks, "_fetch_attempt", lookup):
        rows = asyncio.run(hsguru_decks._fetch_exact("Big Shaman", "wild", "legend"))

    assert rows == [exact_row]
    assert lookup.await_count == 2


def test_all_rank_lookup_uses_one_broad_slice() -> None:
    lookup = AsyncMock(return_value=[])

    with patch.object(hsguru_decks, "_fetch_attempt", lookup):
        rows = asyncio.run(hsguru_decks._fetch_exact("Harold DH", "standard", "all"))

    assert rows == []
    lookup.assert_awaited_once_with(
        "Harold DH",
        "standard",
        [("rank", "all"), ("period", "past_30_days"), ("min_games", 10)],
    )


def test_fetch_attempt_uses_cached_firecrawl_html() -> None:
    scrape = AsyncMock(return_value=FirecrawlScrape(
        html=(
            '<div class="deck_stats_viewport">'
            + _card("Harold DH", "demonhunter", EVENLOCK_CODE, 617, 61.6).replace("# Format: Wild", "# Format: Standard")
            + '</div>'
        ),
        markdown="",
        screenshot=None,
        metadata={"creditsUsed": 1},
        status_code=200,
        final_url="https://www.hsguru.com/decks",
    ))

    with patch.object(hsguru_decks, "scrape_source_with_options", scrape):
        rows = asyncio.run(hsguru_decks._fetch_attempt(
            "Harold DH",
            "standard",
            [("rank", "all"), ("period", "past_30_days"), ("min_games", 10)],
        ))

    assert len(rows) == 1
    assert rows[0]["archetype"] == "Harold DH"
    assert rows[0]["games"] == 617
    assert scrape.await_args.kwargs["max_age_ms"] == 6 * 60 * 60 * 1_000
    assert scrape.await_args.kwargs["timeout_ms"] == 25_000
