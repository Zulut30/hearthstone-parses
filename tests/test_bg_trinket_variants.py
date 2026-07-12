from __future__ import annotations

from bs4 import BeautifulSoup

from app.hsreplay_extract import extract_bg_trinkets, extract_for_source
from app.structured import parse_bg_trinkets


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
