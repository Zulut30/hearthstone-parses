from __future__ import annotations

from app.battlegrounds_comps_parse import parse_hsreplay_comp_detail_markdown


def test_parse_firecrawl_comp_detail_sections() -> None:
    markdown = """
[Comps](https://hsreplay.net/battlegrounds/comps/)

# Mechs - Magnetics Comp Season 13

Medium

s

## Core Cards for Mechs - Magnetics

[![Scrap Scraper](https://art.hearthstonejson.com/v1/bgs/latest/enUS/256x/BG26_148.png)](https://hsreplay.net/battlegrounds/minions/98592/scrap-scraper)

[![Ingenious Inventor](https://art.hearthstonejson.com/v1/bgs/latest/enUS/256x/BG35_890.png)](https://hsreplay.net/battlegrounds/minions/131606/ingenious-inventor)

## Addon Cards for Mechs - Magnetics

[![Holo Rover](https://art.hearthstonejson.com/v1/bgs/latest/enUS/256x/BG31_175.png)](https://hsreplay.net/battlegrounds/minions/115674/holo-rover)

## How to Play Mechs - Magnetics

Generate Magnetics with an early

[Holo Rover](https://hsreplay.net/battlegrounds/minions/115674/holo-rover)

## When to Commit to Mechs - Magnetics

Magnetic Generation (

[Scrap Scraper](https://hsreplay.net/battlegrounds/minions/98592/scrap-scraper)

) +

[Ingenious Inventor](https://hsreplay.net/battlegrounds/minions/131606/ingenious-inventor)

## Common Enablers for Mechs - Magnetics

[Scrap Scraper](https://hsreplay.net/battlegrounds/minions/98592/scrap-scraper)
"""

    comp = parse_hsreplay_comp_detail_markdown(markdown)

    assert comp["title"] == "Mechs - Magnetics"
    assert comp["name"] == "Mechs"
    assert comp["tier"] == "S"
    assert comp["difficulty"] == "Medium"
    assert [card["name"] for card in comp["main_cards"]] == ["Scrap Scraper", "Ingenious Inventor"]
    assert [card["name"] for card in comp["additional_cards"]] == ["Holo Rover"]
    assert [card["name"] for card in comp["when_to_commit_cards"]] == ["Scrap Scraper", "Ingenious Inventor"]
