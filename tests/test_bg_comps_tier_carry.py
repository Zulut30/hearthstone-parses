from app.battlegrounds_comps_parse import parse_hsreplay_markdown


def test_tier_letters_carry_forward_across_long_comp_blocks() -> None:
    # Realistic Firecrawl shape: many image lines between comps push a fixed
    # lookback past the previous S/A/B marker.
    pad = "\n".join([f"![pad {i}](https://art.hearthstonejson.com/v1/256x/BG1.png)" for i in range(120)])
    markdown = "\n".join(
        [
            "s",
            f"[Mechs - Magnetics Medium](https://hsreplay.net/battlegrounds/comps/2/mechs-magnetics)",
            pad,
            "a",
            f"[Quilboar - APM Felboar Hard](https://hsreplay.net/battlegrounds/comps/76/quilboar-apm-felboar)",
            pad,
            f"[Dragons - Spells Easy](https://hsreplay.net/battlegrounds/comps/73/dragons-spells)",
            pad,
            "b",
            f"[Demons - Damage Easy](https://hsreplay.net/battlegrounds/comps/51/demons-damage)",
        ]
    )
    comps = parse_hsreplay_markdown(markdown, detail_limit=10)
    by_slug = {c["slug"]: c["tier"] for c in comps}
    assert by_slug["mechs-magnetics"] == "S"
    assert by_slug["quilboar-apm-felboar"] == "A"
    assert by_slug["dragons-spells"] == "A"
    assert by_slug["demons-damage"] == "B"
