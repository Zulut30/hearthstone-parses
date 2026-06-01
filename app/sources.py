from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urldefrag


@dataclass(frozen=True)
class Source:
    id: str
    url: str
    site: str
    category: str
    parser: str = "generic_html"
    description: str = ""

    @property
    def fetch_url(self) -> str:
        return urldefrag(self.url).url

    @property
    def fragment(self) -> str:
        return urldefrag(self.url).fragment


SOURCES: tuple[Source, ...] = (
    Source(
        "hsguru_streamer_decks_legend_1000",
        "https://www.hsguru.com/streamer-decks?legend=1000",
        "hsguru",
        "streamer_decks",
        description="Streamer decks filtered to top legend.",
    ),
    Source(
        "hsguru_meta_standard_legend",
        "https://www.hsguru.com/meta?format=2&rank=legend",
        "hsguru",
        "meta",
        description="HSGuru meta, format=2, legend.",
    ),
    Source(
        "hsguru_meta_standard_diamond_4to1",
        "https://www.hsguru.com/meta?format=2&rank=diamond_4to1",
        "hsguru",
        "meta",
        description="HSGuru meta, format=2, diamond 4-1.",
    ),
    Source(
        "hsguru_meta_wild_legend",
        "https://www.hsguru.com/meta?format=1&rank=legend",
        "hsguru",
        "meta",
        description="HSGuru meta, format=1, legend.",
    ),
    Source(
        "hsguru_meta_wild_diamond_4to1",
        "https://www.hsguru.com/meta?format=1&rank=diamond_4to1",
        "hsguru",
        "meta",
        description="HSGuru meta, format=1, diamond 4-1.",
    ),
    Source(
        "hsguru_matchups_legend",
        "https://www.hsguru.com/matchups?rank=legend",
        "hsguru",
        "matchups",
        description="HSGuru matchup matrix, legend.",
    ),
    Source(
        "hsguru_matchups_diamond_4to1",
        "https://www.hsguru.com/matchups?rank=diamond_4to1",
        "hsguru",
        "matchups",
        description="HSGuru matchup matrix, diamond 4-1.",
    ),
    Source(
        "hsreplay_battlegrounds_comps",
        "https://hsreplay.net/battlegrounds/comps/",
        "hsreplay",
        "battlegrounds",
        description="HSReplay Battlegrounds comps.",
    ),
    Source(
        "hsreplay_battlegrounds_heroes",
        "https://hsreplay.net/battlegrounds/heroes/",
        "hsreplay",
        "battlegrounds",
        description="HSReplay Battlegrounds heroes.",
    ),
    Source(
        "hsreplay_battlegrounds_trinkets_lesser",
        "https://hsreplay.net/battlegrounds/trinkets/lesser/",
        "hsreplay",
        "battlegrounds",
        description="HSReplay lesser trinkets.",
    ),
    Source(
        "hsreplay_battlegrounds_trinkets_greater",
        "https://hsreplay.net/battlegrounds/trinkets/greater/",
        "hsreplay",
        "battlegrounds",
        description="HSReplay greater trinkets.",
    ),
    Source(
        "hsreplay_arena",
        "https://hsreplay.net/arena/",
        "hsreplay",
        "arena",
        description="HSReplay Arena overview.",
    ),
    Source(
        "hsreplay_arena_legendaries",
        "https://hsreplay.net/arena/legendaries/",
        "hsreplay",
        "arena",
        description="HSReplay Arena legendaries.",
    ),
    Source(
        "hsreplay_arena_winning_decks",
        "https://hsreplay.net/arena/winning_decks/#playerClass=ALL",
        "hsreplay",
        "arena",
        description="HSReplay Arena winning decks. Fragment is client-side.",
    ),
    Source(
        "hsreplay_arena_cards_advanced",
        "https://hsreplay.net/arena/cards/#view=advanced",
        "hsreplay",
        "arena",
        description="HSReplay Arena cards. Fragment is client-side.",
    ),
    Source(
        "hsreplay_decks_trending",
        "https://hsreplay.net/decks/trending/",
        "hsreplay",
        "ranked",
        description="HSReplay trending decks.",
    ),
    Source(
        "hsreplay_cards_legend_included_winrate",
        "https://hsreplay.net/cards/#rankRange=LEGEND&sortBy=includedWinrate",
        "hsreplay",
        "ranked",
        description="HSReplay cards, legend, sorted by included winrate. Fragment is client-side.",
    ),
    Source(
        "hsreplay_cards_legend_included_popularity",
        "https://hsreplay.net/cards/#rankRange=LEGEND&sortBy=includedPopularity",
        "hsreplay",
        "ranked",
        description="HSReplay cards, legend, sorted by included popularity. Fragment is client-side.",
    ),
    Source(
        "firestone_battlegrounds_comps",
        "https://www.firestoneapp.com/battlegrounds/comps",
        "firestone",
        "battlegrounds",
        description="Firestone Battlegrounds compositions.",
    ),
)


SOURCE_BY_ID = {source.id: source for source in SOURCES}
