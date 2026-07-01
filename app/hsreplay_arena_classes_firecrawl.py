from __future__ import annotations

import asyncio
from typing import Any

from .firecrawl_backend import scrape_source_with_options
from .hsreplay_arena_api import fetch_class_stats
from .hsreplay_auth import hsreplay_cookies_for_fetch
from .sources import Source

ARENA_CLASS_BASE = "https://hsreplay.net/arena"

ARENA_CLASSES = [
    {"slug": "deathknight", "class": "Deathknight", "class_name": "Death Knight", "class_ru": "Рыцарь смерти"},
    {"slug": "demonhunter", "class": "Demonhunter", "class_name": "Demon Hunter", "class_ru": "Охотник на демонов"},
    {"slug": "druid", "class": "Druid", "class_name": "Druid", "class_ru": "Друид"},
    {"slug": "hunter", "class": "Hunter", "class_name": "Hunter", "class_ru": "Охотник"},
    {"slug": "mage", "class": "Mage", "class_name": "Mage", "class_ru": "Маг"},
    {"slug": "paladin", "class": "Paladin", "class_name": "Paladin", "class_ru": "Паладин"},
    {"slug": "priest", "class": "Priest", "class_name": "Priest", "class_ru": "Жрец"},
    {"slug": "rogue", "class": "Rogue", "class_name": "Rogue", "class_ru": "Разбойник"},
    {"slug": "shaman", "class": "Shaman", "class_name": "Shaman", "class_ru": "Шаман"},
    {"slug": "warlock", "class": "Warlock", "class_name": "Warlock", "class_ru": "Чернокнижник"},
    {"slug": "warrior", "class": "Warrior", "class_name": "Warrior", "class_ru": "Воин"},
]


def _cookie_header() -> str:
    return "; ".join(
        f"{cookie['name']}={cookie['value']}"
        for cookie in hsreplay_cookies_for_fetch()
        if cookie.get("name") and cookie.get("value")
    )


async def _scrape_class_page(source_id: str, item: dict[str, str], sem: asyncio.Semaphore) -> dict[str, Any]:
    url = f"{ARENA_CLASS_BASE}/{item['slug']}/"
    source = Source(
        f"{source_id}_{item['slug']}",
        url,
        "hsreplay",
        "arena",
        description=f"HSReplay Arena {item['class_name']} class page.",
    )
    async with sem:
        scraped = await scrape_source_with_options(
            source,
            formats=["markdown", "html"],
            only_main_content=True,
            headers={
                "Cookie": _cookie_header(),
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
    return {
        "ok": True,
        "url": url,
        "final_url": scraped.final_url,
        "status_code": scraped.status_code,
        "content_length": scraped.content_length,
        "markdown_length": len(scraped.markdown),
        "credits_used": scraped.metadata.get("creditsUsed"),
    }


async def fetch_arena_class_pages_firecrawl(source_id: str = "hsreplay_arena_class_pages_firecrawl") -> dict[str, Any]:
    stats = await fetch_class_stats(source_id=source_id)
    stats_by_class = {str(row.get("class")): row for row in stats.get("classes") or []}
    errors: list[str] = []
    sem = asyncio.Semaphore(3)

    async def build(item: dict[str, str]) -> dict[str, Any]:
        firecrawl: dict[str, Any]
        try:
            firecrawl = await _scrape_class_page(source_id, item, sem)
        except Exception as exc:
            firecrawl = {"ok": False, "url": f"{ARENA_CLASS_BASE}/{item['slug']}/", "error": f"{type(exc).__name__}: {str(exc)[:180]}"}
            errors.append(f"{item['slug']}: {firecrawl['error']}")
        row = stats_by_class.get(item["class"]) or {}
        return {
            **item,
            "url": f"{ARENA_CLASS_BASE}/{item['slug']}/",
            "winrate": row.get("winrate"),
            "win_rate": row.get("win_rate"),
            "pct_7_plus": row.get("pct_7_plus"),
            "pick_rate": row.get("pick_rate"),
            "num_drafts": row.get("num_drafts"),
            "deck_class": row.get("deck_class"),
            "firecrawl": firecrawl,
        }

    classes = await asyncio.gather(*[build(item) for item in ARENA_CLASSES])
    classes.sort(key=lambda row: float(row.get("win_rate") or 0), reverse=True)
    return {
        "type": "arena_class_pages",
        "classes": classes,
        "matchups": stats.get("matchups") or [],
        "source": {
            "key": "hsreplay",
            "url": "https://hsreplay.net/arena/deathknight/",
            "backend": "firecrawl+hsreplay_arena_api",
            "classes": len(classes),
            "firecrawl_ok": sum(1 for row in classes if row.get("firecrawl", {}).get("ok")),
            "errors": errors,
            "api_url": (stats.get("source") or {}).get("api_url"),
        },
    }
