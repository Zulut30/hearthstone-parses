from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup

from app.battlegrounds_comps_parse import parse_hsreplay_comp_detail_markdown
from app.hsreplay_arena_classes_firecrawl import fetch_arena_class_pages_firecrawl
from app.hsreplay_extract import extract_for_source
from app.structured import parse_bg_heroes, parse_bg_trinkets
from app.vicious_syndicate import parse_latest_report_metadata


FIXTURES = Path(__file__).parent / "fixtures" / "snapshots"


def _json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _project(rows: list[dict], keys: tuple[str, ...]) -> list[dict]:
    return [{key: row.get(key) for key in keys} for row in rows]


def test_hsreplay_trinket_snapshot_and_diagnostics() -> None:
    html = (FIXTURES / "hsreplay_trinkets.html").read_text(encoding="utf-8")
    result = extract_for_source(
        "hsreplay_battlegrounds_trinkets_lesser",
        BeautifulSoup(html, "lxml"),
        html,
    )

    assert result["parser_level"] == "primary"
    assert result["dropped_rows"] == 1
    assert _project(
        result["trinkets"],
        ("name", "trinket_id", "tribe", "cost", "pick_rate", "avg_placement"),
    ) == [
        {
            "name": "Colorful Compass",
            "trinket_id": "BG30_MagicItem_426",
            "tribe": "Murloc",
            "cost": 2,
            "pick_rate": "32.1%",
            "avg_placement": "3.87",
        }
    ]


def test_structured_bg_hero_snapshot() -> None:
    fixture = _json("bg_heroes.json")
    assert parse_bg_heroes(fixture["lines"]) == fixture["expected"]


def test_structured_bg_trinket_snapshot() -> None:
    fixture = _json("bg_trinkets.json")
    actual = _project(
        parse_bg_trinkets(fixture["lines"]),
        ("name", "tribe", "tier", "cost", "pick_rate", "avg_placement"),
    )
    assert actual == fixture["expected_projection"]


def test_vicious_report_index_snapshot() -> None:
    html = (FIXTURES / "vicious_report_index.html").read_text(encoding="utf-8")
    assert parse_latest_report_metadata(html) == {
        "latest_report_issue": "330",
        "latest_report_url": "https://www.vicioussyndicate.com/vs-data-reaper-report-330/",
        "latest_report_published_at": "2026-07-09",
    }


def test_bg_comp_detail_snapshot() -> None:
    markdown = (FIXTURES / "bg_comp_detail.md").read_text(encoding="utf-8")
    result = parse_hsreplay_comp_detail_markdown(markdown)
    assert {
        "name": result["name"],
        "title": result["title"],
        "tier": result["tier"],
        "difficulty": result["difficulty"],
        "main_cards": [row["name"] for row in result["main_cards"]],
        "additional_cards": [row["name"] for row in result["additional_cards"]],
        "how_to_play": result["how_to_play"],
        "when_to_commit": result["when_to_commit"],
    } == {
        "name": "Mechs",
        "title": "Mechs - Magnetics",
        "tier": "S",
        "difficulty": "Medium",
        "main_cards": ["Scrap Scraper"],
        "additional_cards": ["Holo Rover"],
        "how_to_play": "Generate Magnetics with an early Holo Rover.",
        "when_to_commit": "Commit after finding Scrap Scraper.",
    }


async def _fake_scrape(_source_id: str, item: dict[str, str], _sem: object) -> dict:
    return {
        "ok": True,
        "url": f"https://hsreplay.net/arena/{item['slug']}/",
        "final_url": f"https://hsreplay.net/arena/{item['slug']}/",
        "status_code": 200,
        "content_length": 12000,
        "markdown_length": 6000,
        "credits_used": 1,
    }


def _arena_result(stats: dict) -> dict:
    async def run() -> dict:
        with (
            patch(
                "app.hsreplay_arena_classes_firecrawl.fetch_class_stats",
                return_value=stats,
            ),
            patch(
                "app.hsreplay_arena_classes_firecrawl._scrape_class_page",
                side_effect=_fake_scrape,
            ),
        ):
            return await fetch_arena_class_pages_firecrawl()

    return asyncio.run(run())


def test_arena_class_pages_snapshot() -> None:
    result = _arena_result(_json("arena_class_pages.json"))
    assert result["type"] == "arena_class_pages"
    assert result["source"] == {
        "key": "hsreplay",
        "url": "https://hsreplay.net/arena/deathknight/",
        "backend": "firecrawl+hsreplay_arena_api",
        "classes": 11,
        "firecrawl_ok": 11,
        "errors": [],
        "api_url": "https://hsreplay.net/api/v1/arena/classes_stats/",
    }
    assert _project(result["classes"], ("class", "win_rate", "pick_rate")) == [
        {"class": row["class"], "win_rate": row["win_rate"], "pick_rate": row["pick_rate"]}
        for row in _json("arena_class_pages.json")["classes"]
    ]


def test_snapshot_mutations_are_not_silent() -> None:
    trinket_html = (FIXTURES / "hsreplay_trinkets.html").read_text(encoding="utf-8")
    baseline_trinket = extract_for_source(
        "hsreplay_battlegrounds_trinkets_lesser",
        BeautifulSoup(trinket_html, "lxml"),
        trinket_html,
    )
    for mutated in (
        trinket_html.replace("tabindex=\"0\"", "data-tabindex=\"0\""),
        trinket_html.replace("Colorful Compass", ""),
        trinket_html.replace(
            "<div>2</div><div>Colorful Compass</div><div>Murloc</div>",
            "<div>2</div><div>Murloc</div><div>Colorful Compass</div>",
        ),
    ):
        result = extract_for_source(
            "hsreplay_battlegrounds_trinkets_lesser",
            BeautifulSoup(mutated, "lxml"),
            mutated,
        )
        assert result != baseline_trinket or result["dropped_rows"] > baseline_trinket["dropped_rows"]

    hero_lines = _json("bg_heroes.json")["lines"]
    baseline_heroes = parse_bg_heroes(hero_lines)
    hero_mutations = (
        ["A F Kay" if value == "A.F. Kay" else value for value in hero_lines],
        [value for value in hero_lines if value != "8.4%"],
        hero_lines[:5] + list(reversed(hero_lines[5:])),
    )
    assert all(parse_bg_heroes(lines) != baseline_heroes for lines in hero_mutations)

    trinket_lines = _json("bg_trinkets.json")["lines"]
    baseline_line_trinkets = parse_bg_trinkets(trinket_lines)
    trinket_mutations = (
        ["Colourful Compass" if value == "Colorful Compass" else value for value in trinket_lines],
        [value for value in trinket_lines if value != "32.1%"],
        trinket_lines[:6] + list(reversed(trinket_lines[6:])),
    )
    assert all(parse_bg_trinkets(lines) != baseline_line_trinkets for lines in trinket_mutations)

    vicious = (FIXTURES / "vicious_report_index.html").read_text(encoding="utf-8")
    baseline_vicious = parse_latest_report_metadata(vicious)
    vicious_mutations = (
        vicious.replace("entry-meta-date", "published-date"),
        vicious.replace("<article>\n    <a href=\"/vs-data-reaper-report-330/\"", "<article hidden>\n    <span"),
        vicious.replace("report-329", "report-331"),
    )
    for html in vicious_mutations:
        try:
            result = parse_latest_report_metadata(html)
        except RuntimeError:
            continue
        assert result != baseline_vicious

    comp = (FIXTURES / "bg_comp_detail.md").read_text(encoding="utf-8")
    baseline_comp = parse_hsreplay_comp_detail_markdown(comp)
    comp_mutations = (
        comp.replace("## Core Cards", "## Primary Cards"),
        comp.replace("## Addon Cards", "## Removed Cards"),
        comp.replace("## How to Play", "## When to Commit", 1),
    )
    assert all(parse_hsreplay_comp_detail_markdown(value) != baseline_comp for value in comp_mutations)

    arena = _json("arena_class_pages.json")
    baseline_arena = _arena_result(arena)
    renamed = json.loads(json.dumps(arena))
    renamed["classes"][0]["class"] = "Death Knight"
    removed = json.loads(json.dumps(arena))
    removed["classes"] = removed["classes"][1:]
    reordered = json.loads(json.dumps(arena))
    reordered["classes"][0]["win_rate"], reordered["classes"][-1]["win_rate"] = (
        reordered["classes"][-1]["win_rate"],
        reordered["classes"][0]["win_rate"],
    )
    assert all(_arena_result(value) != baseline_arena for value in (renamed, removed, reordered))


def test_snapshot_fixtures_remain_small() -> None:
    snapshots = list(FIXTURES.iterdir())
    assert len(snapshots) == 6
    assert all(path.stat().st_size < 50_000 for path in snapshots)
